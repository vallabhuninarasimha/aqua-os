"""Pond-specific aeration state machine and advisory decision engine.

Enforces:
1. Anti-cycling hysteresis (min runtime 30m, min offtime 15m).
2. DO threshold boundaries (turn ON when DO < 4.5 mg/L, turn OFF when DO > 5.8 mg/L).
3. Stale/faulted DO sensor fail-safe (forces aeration ON if sensor reading is missing or old).
4. Transformer continuous load interlock (warns/blocks if >80% continuous rating of 23 kW transformer).
5. DRY-RUN execution mode: NO physical actuator or relay commands are triggered.
"""

from datetime import datetime, timezone
import uuid
from typing import Dict, List, Optional, Tuple

from apps.api.src.domain.hardware_interfaces import (
    AerationDecisionResult,
    AeratorStatus,
    DesiredEquipmentState,
    IAeratorController,
    PhysicalRunningState,
    TransformerPowerStatus,
)
from packages.telemetry_schema.config import BiologicalThresholds, PondConfig, TransformerConfig


class AerationDecisionEngine(IAeratorController):
    """Safe state machine for pond aeration decisions."""

    def __init__(self) -> None:
        # Track last transition timestamp and status per pond
        # pond_id -> (last_action, timestamp_utc)
        self._last_state_transitions: Dict[str, Tuple[str, datetime]] = {}

    def evaluate_pond(
        self,
        farm_id: str,
        pond_id: str,
        current_do_mg_l: Optional[float],
        sensor_healthy: bool,
        pond_config: Optional[PondConfig] = None,
        aerators: Optional[List[AeratorStatus]] = None,
        transformer_status: Optional[TransformerPowerStatus] = None,
        operator_id: Optional[str] = None,
        sensor_freshness_seconds: Optional[float] = None,
        is_simulated: bool = True,
    ) -> AerationDecisionResult:
        """Evaluate pond aeration logic, manual overrides, and DO-risk advisory (DRY_RUN only)."""
        now = datetime.now(timezone.utc)
        thresholds = pond_config.thresholds if pond_config else BiologicalThresholds()

        on_thresh = thresholds.aeration_on_threshold_mg_l
        off_thresh = thresholds.aeration_off_threshold_mg_l
        emergency_thresh = thresholds.do_emergency_mg_l
        warning_thresh = thresholds.do_warning_mg_l
        min_run_min = thresholds.min_runtime_minutes
        min_off_min = thresholds.min_offtime_minutes

        current_aerators = aerators or []
        running_aerators = [
            a for a in current_aerators if a.verified_physical_state == PhysicalRunningState.RUNNING
        ]
        is_currently_running = len(running_aerators) > 0

        # Check for manual overrides on aerator units
        manual_override_on = any(a.desired_state == DesiredEquipmentState.FORCE_ON for a in current_aerators)
        manual_override_off = any(a.desired_state in (DesiredEquipmentState.FORCE_OFF, DesiredEquipmentState.OFF) for a in current_aerators)
        manual_override_active = manual_override_on or manual_override_off

        last_trans = self._last_state_transitions.get(pond_id)
        last_action = last_trans[0] if last_trans else ("START" if is_currently_running else "STOP")
        last_action_time = last_trans[1] if last_trans else now
        minutes_since_last = (now - last_action_time).total_seconds() / 60.0

        transformer_headroom = (
            transformer_status.headroom_kw if transformer_status else 15.0
        )

        decision_id = f"dec-{uuid.uuid4().hex[:10]}"
        proposed_action = "HOLD"
        reason = "Dissolved oxygen within acceptable hysteresis band."
        interlocks_ok = True
        risk_level = "NORMAL"

        # 0. Risk Advisory Classification using configured rules
        if current_do_mg_l is None or not sensor_healthy:
            risk_level = "UNKNOWN"
        elif current_do_mg_l < emergency_thresh:
            risk_level = "CRITICAL"
        elif current_do_mg_l < warning_thresh:
            risk_level = "MODERATE"
        else:
            risk_level = "NORMAL"

        # 1. Manual Override Handling (Respects operator manual commands while verifying safety)
        if manual_override_on:
            proposed_action = "START"
            reason = "MANUAL OVERRIDE: Operator has requested FORCE_ON for pond aerators."
        elif manual_override_off:
            proposed_action = "STOP"
            reason = "MANUAL OVERRIDE: Operator has requested FORCE_OFF for pond aerators."

        # 2. Stale / Faulted Sensor Fail-Safe Check
        elif not sensor_healthy or current_do_mg_l is None:
            if not is_currently_running:
                # Anti-cycling check on restart
                if minutes_since_last < min_off_min and last_action == "STOP":
                    proposed_action = "HOLD"
                    reason = f"DO sensor faulted, but min off-time ({min_off_min}m) not elapsed ({minutes_since_last:.1f}m)."
                else:
                    proposed_action = "START"
                    reason = "CRITICAL FAIL-SAFE: DO sensor is offline/stale/faulted. Aeration recommended immediately."
            else:
                proposed_action = "HOLD"
                reason = "DO sensor is offline/stale. Maintaining fail-safe running aeration."

        # 3. DO Below ON Threshold (< 4.5 mg/L)
        elif current_do_mg_l < on_thresh:
            if not is_currently_running:
                if minutes_since_last < min_off_min and last_action == "STOP":
                    proposed_action = "HOLD"
                    reason = (
                        f"DO low ({current_do_mg_l:.2f} mg/L < {on_thresh} mg/L), "
                        f"but anti-cycling min off-time ({min_off_min}m) has only reached {minutes_since_last:.1f}m."
                    )
                else:
                    proposed_action = "START"
                    reason = f"DO level ({current_do_mg_l:.2f} mg/L) below threshold ({on_thresh} mg/L). Start aeration."
            else:
                proposed_action = "HOLD"
                reason = f"DO low ({current_do_mg_l:.2f} mg/L). Aerators already running."

        # 4. DO Above OFF Threshold (> 5.8 mg/L)
        elif current_do_mg_l > off_thresh:
            if is_currently_running:
                if minutes_since_last < min_run_min and last_action == "START":
                    proposed_action = "HOLD"
                    reason = (
                        f"DO high ({current_do_mg_l:.2f} mg/L > {off_thresh} mg/L), "
                        f"but minimum runtime ({min_run_min}m) has only reached {minutes_since_last:.1f}m. Holding ON."
                    )
                else:
                    proposed_action = "STOP"
                    reason = (
                        f"DO level ({current_do_mg_l:.2f} mg/L) safely above {off_thresh} mg/L and "
                        f"minimum runtime met ({minutes_since_last:.1f}m >= {min_run_min}m). Stop aeration."
                    )
            else:
                proposed_action = "HOLD"
                reason = f"DO level ({current_do_mg_l:.2f} mg/L) is optimal. Aeration idle."

        # 5. In Hysteresis Zone (4.5 - 5.8 mg/L)
        else:
            proposed_action = "HOLD"
            reason = f"DO level ({current_do_mg_l:.2f} mg/L) is within stable hysteresis zone ({on_thresh} - {off_thresh} mg/L)."

        # 6. Transformer Continuous Load Interlock Check
        # Check if proposing START will violate 80% continuous rating (18.4 kW on 23 kW TX)
        if proposed_action == "START":
            required_kw = 1.5 * max(1, pond_config.aerator_count if pond_config else 2)
            if transformer_headroom < required_kw:
                interlocks_ok = False
                reason += f" [WARNING: Transformer headroom {transformer_headroom:.1f}kW is less than required {required_kw:.1f}kW. Overload risk!]"

        # Update transition tracker if proposed action is a change
        if proposed_action in ("START", "STOP") and proposed_action != last_action:
            self._last_state_transitions[pond_id] = (proposed_action, now)

        return AerationDecisionResult(
            decision_id=decision_id,
            farm_id=farm_id,
            pond_id=pond_id,
            timestamp=now,
            do_value_mg_l=current_do_mg_l,
            do_sensor_healthy=sensor_healthy,
            proposed_action=proposed_action,
            reason=reason,
            interlocks_ok=interlocks_ok,
            transformer_headroom_kw=transformer_headroom,
            execution_mode="DRY_RUN",
            operator_id=operator_id,
            risk_level=risk_level,
            is_simulated=is_simulated,
            sensor_freshness_seconds=sensor_freshness_seconds,
            manual_override_active=manual_override_active,
        )

