"""Water Management Domain Service for Aqua OS.

Handles simulated water-level tracking, intake-pump advisory, dual-outlet
mechanical status, unauthorized-drain alerts, and water exchange audit logging.

SAFETY INVARIANTS:
1. All physical actuation commands remain strictly disabled in DRY_RUN.
2. Full-drain outlet defaults to locked; automatic drainage is strictly prohibited.
3. Stale or missing telemetry is treated as UNKNOWN/DEGRADED, never safe.
4. Thresholds and electrical ratings are provisional configuration requiring site validation.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.water_interfaces import (
    GateState,
    IWaterRepository,
    PondOutletStatus,
    PumpAdvisoryDecision,
    PumpOperationalState,
    WaterManagementMode,
    WaterPumpInfo,
)
from apps.api.src.infrastructure.models import AlertRecordORM, PondORM, WaterPumpORM
from apps.api.src.infrastructure.repositories.sql_alert_repository import SQLAlertRepository
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from apps.api.src.infrastructure.repositories.sql_water_repository import SQLWaterRepository
from apps.api.src.services.power_service import PowerMonitoringService
from packages.telemetry_schema.models import AlertSeverity, MetricType

logger = logging.getLogger(__name__)


class WaterManagementService:
    """Service orchestrating water level monitoring, intake pump advisory, and outlet tracking."""

    def __init__(self, session: Session, water_repo: Optional[IWaterRepository] = None) -> None:
        self._session = session
        self._water_repo = water_repo or SQLWaterRepository(session)
        self._pond_repo = SQLPondRepository(session)
        self._telemetry_repo = SQLTelemetryRepository(session)
        self._alert_repo = SQLAlertRepository(session)
        self._power_service = PowerMonitoringService(session)

    # -------------------------------------------------------------------------
    # Water Level & Outlet Status
    # -------------------------------------------------------------------------
    def get_pond_water_status(self, farm_id: str, pond_id: str) -> Dict[str, Any]:
        """Evaluate water level freshness, boundaries, outlet positions, and safety alerts."""
        pond_outlet = self._water_repo.get_pond_outlet_status(farm_id, pond_id)
        if not pond_outlet:
            raise ValueError(f"Pond '{pond_id}' not found in farm '{farm_id}'.")

        now = datetime.now(timezone.utc)
        latest_record = self._telemetry_repo.get_latest(farm_id=farm_id, pond_id=pond_id)

        current_level_m: Optional[float] = None
        freshness_seconds: Optional[float] = None
        is_stale: bool = True
        status_category: str = "UNKNOWN"
        active_water_alerts: List[str] = []

        target_m = pond_outlet.get("water_level_target_m", 1.22)
        min_m = pond_outlet.get("water_level_min_m", 0.95)
        max_m = pond_outlet.get("water_level_max_m", 1.40)

        if latest_record:
            packet, _ = latest_record
            packet_time = packet.timestamp.replace(tzinfo=timezone.utc)
            freshness_seconds = max(0.0, (now - packet_time).total_seconds())
            is_stale = freshness_seconds > 60.0

            reading = packet.metrics.get(MetricType.WATER_LEVEL)
            if reading and reading.quality.value == "GOOD":
                current_level_m = reading.value
            elif reading:
                # Degraded quality
                current_level_m = reading.value
                is_stale = True

        # Safety evaluation based on freshness and thresholds
        if current_level_m is None or is_stale:
            status_category = "DEGRADED" if current_level_m is not None else "UNKNOWN"
            alert_msg = (
                f"Water level telemetry stale ({int(freshness_seconds or 0)}s elapsed)"
                if current_level_m is not None
                else "Water level sensor telemetry missing / offline"
            )
            active_water_alerts.append(alert_msg)
            self._record_safety_alert(
                farm_id=farm_id,
                pond_id=pond_id,
                alert_code="WATER_LEVEL_STALE",
                severity=AlertSeverity.WARNING.value,
                message=alert_msg,
                recommended_action="Inspect local pond ultrasonic/pressure level transmitter and edge gateway.",
                trigger_value=current_level_m,
                threshold_value=min_m,
            )
        else:
            if current_level_m < min_m:
                status_category = "WARNING" if current_level_m >= (min_m - 0.15) else "CRITICAL"
                msg = f"Low water level: {current_level_m:.2f}m is below minimum safe threshold ({min_m:.2f}m)."
                active_water_alerts.append(msg)
                self._record_safety_alert(
                    farm_id=farm_id,
                    pond_id=pond_id,
                    alert_code="POND_WATER_LEVEL_LOW",
                    severity=status_category,
                    message=msg,
                    recommended_action="Verify outlet gates are sealed. Inspect pond dikes for seepage. Evaluate intake pump advisory.",
                    trigger_value=current_level_m,
                    threshold_value=min_m,
                )
            elif current_level_m > max_m:
                status_category = "WARNING"
                msg = f"High water level: {current_level_m:.2f}m exceeds maximum freeboard limit ({max_m:.2f}m)."
                active_water_alerts.append(msg)
                self._record_safety_alert(
                    farm_id=farm_id,
                    pond_id=pond_id,
                    alert_code="POND_WATER_LEVEL_HIGH",
                    severity="WARNING",
                    message=msg,
                    recommended_action="Check normal overflow outlet. Halt intake pumping. Inspect rainwater runoff channels.",
                    trigger_value=current_level_m,
                    threshold_value=max_m,
                )
            else:
                status_category = "NORMAL"

        # Check full-drain outlet containment security
        full_drain_state = pond_outlet.get("full_drain_outlet_state", GateState.CLOSED.value)
        full_drain_locked = pond_outlet.get("full_drain_locked", True)
        if full_drain_state in (GateState.OPEN.value, GateState.PARTIALLY_OPEN.value):
            drain_alert = f"CRITICAL: Full-drain outlet is {full_drain_state} on {pond_id}! Active batch containment breached."
            active_water_alerts.append(drain_alert)
            self._record_safety_alert(
                farm_id=farm_id,
                pond_id=pond_id,
                alert_code="UNAUTHORIZED_DRAIN_RISK",
                severity="CRITICAL",
                message=drain_alert,
                recommended_action="Immediately inspect central harvest monk / sluice gate manually and engage mechanical padlock.",
                trigger_value=current_level_m,
                threshold_value=min_m,
            )

        # Compute strict is_safe flag: never True if stale, degraded, unknown, out of bounds, or full drain breached
        is_safe = not (
            is_stale
            or current_level_m is None
            or status_category in ("UNKNOWN", "DEGRADED", "WARNING", "CRITICAL")
            or full_drain_state in (GateState.OPEN.value, GateState.PARTIALLY_OPEN.value)
            or not full_drain_locked
        )

        is_simulated = bool(latest_record[0].is_simulated) if latest_record else True

        return {
            "farm_id": farm_id,
            "pond_id": pond_id,
            "name": pond_outlet.get("name", pond_id),
            "status": status_category,
            "is_safe": is_safe,
            "current_level_m": current_level_m,
            "water_level_target_m": target_m,
            "water_level_min_m": min_m,
            "water_level_max_m": max_m,
            "limits_provisional": True,
            "limits_notice": (
                "Pond water level limits are provisional baseline defaults. "
                "They have not been certified by civil engineering survey, bathymetry, or local dyke freeboard calculations."
            ),
            "is_stale": is_stale,
            "freshness_seconds": round(freshness_seconds, 1) if freshness_seconds is not None else None,
            "normal_outlet_state": pond_outlet.get("normal_outlet_state", GateState.CLOSED.value),
            "full_drain_outlet_state": full_drain_state,
            "full_drain_locked": full_drain_locked,
            "drain_lock_reason": pond_outlet.get("drain_lock_reason", ""),
            "active_water_alerts": active_water_alerts,
            "is_simulated": is_simulated,
            "data_provenance": "SIMULATED_SYNTHETIC" if is_simulated else "PHYSICAL_SENSOR",
            "physical_position_confirmed": False,
            "actuator_control": "DISABLED_DRY_RUN",
            "software_intent_only": True,
            "physical_interlock_notice": (
                "Software state representation only. Physical valve position must be confirmed "
                "via local visual inspection and hardware limit switches prior to critical operations. "
                "Automatic drainage is strictly prohibited."
            ),
        }

    def list_farm_water_status(self, farm_id: str) -> List[Dict[str, Any]]:
        """List water level and outlet statuses across all configured ponds."""
        outlets = self._water_repo.list_pond_outlet_statuses(farm_id)
        return [self.get_pond_water_status(farm_id, p["pond_id"]) for p in outlets]

    def update_pond_level_targets(
        self,
        farm_id: str,
        pond_id: str,
        target_m: float,
        min_m: float,
        max_m: float,
    ) -> Optional[Dict[str, Any]]:
        """Update configurable target depth and safe boundaries."""
        if min_m >= max_m:
            raise ValueError(f"min_m ({min_m}) must be strictly less than max_m ({max_m}).")
        if target_m < min_m or target_m > max_m:
            raise ValueError(f"target_m ({target_m}) must be between min_m and max_m.")
        return self._water_repo.update_pond_level_targets(
            farm_id=farm_id, pond_id=pond_id, target_m=target_m, min_m=min_m, max_m=max_m
        )

    def update_pond_outlet_state(
        self,
        farm_id: str,
        pond_id: str,
        normal_outlet_state: Optional[str] = None,
        full_drain_outlet_state: Optional[str] = None,
        full_drain_locked: Optional[bool] = None,
        drain_lock_reason: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update mechanical outlet gates and lock state.
        
        Strict rule: Full-drain outlet defaults to locked. Automatic drainage is disabled.
        Software state records operator intent only and does not imply physical position confirmation.
        """
        current = self._water_repo.get_pond_outlet_status(farm_id, pond_id)
        if not current:
            return None

        is_currently_locked = current.get("full_drain_locked", True)
        target_lock = full_drain_locked if full_drain_locked is not None else is_currently_locked
        target_full_drain = full_drain_outlet_state or current.get("full_drain_outlet_state", GateState.CLOSED.value)

        # Enforce validation: unlocking requires explicit reason
        if target_lock is False and (not drain_lock_reason or len(drain_lock_reason.strip()) < 5):
            raise ValueError("Unlocking full-drain outlet requires an explicit operational authorization reason (min 5 chars).")

        # If attempting to open full drain while locked, reject
        if target_lock and target_full_drain in (GateState.OPEN.value, GateState.PARTIALLY_OPEN.value):
            raise ValueError("Cannot open full-drain outlet while full_drain_locked is TRUE. Unlock required first.")

        updated = self._water_repo.update_pond_outlet_state(
            farm_id=farm_id,
            pond_id=pond_id,
            normal_outlet_state=normal_outlet_state,
            full_drain_outlet_state=full_drain_outlet_state,
            full_drain_locked=full_drain_locked,
            drain_lock_reason=drain_lock_reason,
        )

        # Record immutable audit log
        try:
            import json
            from apps.api.src.infrastructure.models import AuditLogORM
            audit = AuditLogORM(
                farm_id=farm_id,
                user_id=operator_id or "system",
                action="UPDATE_POND_OUTLETS",
                resource_type="pond_outlets",
                resource_id=pond_id,
                details_json=json.dumps({
                    "normal_outlet_state": normal_outlet_state,
                    "full_drain_outlet_state": full_drain_outlet_state,
                    "full_drain_locked": full_drain_locked,
                    "drain_lock_reason": drain_lock_reason,
                    "software_intent_only": True,
                    "actuator_mode": "DRY_RUN",
                }),
            )
            self._session.add(audit)
            self._session.commit()
        except Exception as e:
            logger.warning("Could not persist audit log for outlet update: %s", e)

        return updated

    # -------------------------------------------------------------------------
    # Farm Intake Pump & Advisory
    # -------------------------------------------------------------------------
    def get_pump_info(self, farm_id: str, pump_id: str = "pump-river-intake-01") -> Optional[Dict[str, Any]]:
        """Fetch pump electrical rating, assigned transformer, and running measurements."""
        return self._water_repo.get_pump(farm_id=farm_id, pump_id=pump_id)

    def update_pump_config(
        self,
        farm_id: str,
        pump_id: str,
        transformer_id: str,
        motor_hp: Optional[float] = None,
        rating_kw: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Configure pump motor specs and assigned electrical transformer feeder."""
        return self._water_repo.update_pump_config(
            farm_id=farm_id,
            pump_id=pump_id,
            transformer_id=transformer_id,
            motor_hp=motor_hp,
            rating_kw=rating_kw,
        )

    def evaluate_pump_advisory(
        self,
        farm_id: str,
        pump_id: str = "pump-river-intake-01",
        target_pond_id: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> PumpAdvisoryDecision:
        """Evaluate intake pump operation against transformer headroom and target pond level.
        
        Strict rule: Execution mode is strictly DRY_RUN. Real actuators remain disabled.
        """
        pump = self._water_repo.get_pump(farm_id=farm_id, pump_id=pump_id)
        if not pump:
            return PumpAdvisoryDecision(
                proposed_action="HOLD",
                pump_id=pump_id,
                target_pond_id=target_pond_id,
                reason=f"Pump '{pump_id}' not found in registry.",
                transformer_id="UNKNOWN",
                transformer_headroom_kw=0.0,
                interlocks_ok=False,
                execution_mode="DRY_RUN",
                operator_id=operator_id,
            )

        tx_id = pump.get("transformer_id")
        pump_kw = pump.get("rating_kw")

        # 1. Reject if transformer assignment is unconfigured
        if not tx_id or tx_id == "UNCONFIGURED":
            return PumpAdvisoryDecision(
                proposed_action="HOLD",
                pump_id=pump_id,
                target_pond_id=target_pond_id,
                reason="Intake pump electrical transformer assignment is unconfigured. Feeder connection must be verified and configured before advisory can evaluate headroom.",
                transformer_id="UNCONFIGURED",
                transformer_headroom_kw=0.0,
                interlocks_ok=False,
                execution_mode="DRY_RUN",
                operator_id=operator_id,
            )

        # 2. Reject if pump rating is unknown / unconfigured
        if pump_kw is None or pump_kw <= 0:
            return PumpAdvisoryDecision(
                proposed_action="HOLD",
                pump_id=pump_id,
                target_pond_id=target_pond_id,
                reason="Intake pump electrical rating is unconfigured/unknown. Verified motor nameplate data (kW) must be entered before evaluating transformer headroom.",
                transformer_id=tx_id,
                transformer_headroom_kw=0.0,
                interlocks_ok=False,
                execution_mode="DRY_RUN",
                operator_id=operator_id,
            )

        # 3. Check transformer monitoring telemetry
        try:
            tx_status = self._power_service.get_transformer_status(farm_id=farm_id, transformer_id=tx_id)
        except Exception as e:
            return PumpAdvisoryDecision(
                proposed_action="HOLD",
                pump_id=pump_id,
                target_pond_id=target_pond_id,
                reason=f"Transformer monitoring telemetry unavailable or failed ({e}). Advisory held for safety.",
                transformer_id=tx_id,
                transformer_headroom_kw=0.0,
                interlocks_ok=False,
                execution_mode="DRY_RUN",
                operator_id=operator_id,
            )

        if not tx_status or tx_status.capacity_kw is None or tx_status.capacity_kw <= 0:
            return PumpAdvisoryDecision(
                proposed_action="HOLD",
                pump_id=pump_id,
                target_pond_id=target_pond_id,
                reason=f"Transformer '{tx_id}' capacity is unverified/unknown. Advisory held for electrical safety.",
                transformer_id=tx_id,
                transformer_headroom_kw=0.0,
                interlocks_ok=False,
                execution_mode="DRY_RUN",
                operator_id=operator_id,
            )

        headroom_kw = tx_status.headroom_kw or 0.0

        # 4. Check target pond condition if specified
        target_pond_low = False
        target_pond_level_m = None
        if target_pond_id:
            try:
                status = self.get_pond_water_status(farm_id, target_pond_id)
                target_pond_level_m = status.get("current_level_m")
                target_m = status.get("water_level_target_m", 1.22)
                if target_pond_level_m is not None and target_pond_level_m < target_m:
                    target_pond_low = True

                if status.get("is_stale") or target_pond_level_m is None:
                    return PumpAdvisoryDecision(
                        proposed_action="HOLD",
                        pump_id=pump_id,
                        target_pond_id=target_pond_id,
                        reason=f"Target pond '{target_pond_id}' water telemetry is stale or missing ({status.get('freshness_seconds')}s elapsed). Operation unsafe.",
                        transformer_id=tx_id,
                        transformer_headroom_kw=headroom_kw,
                        interlocks_ok=False,
                        execution_mode="DRY_RUN",
                        operator_id=operator_id,
                    )
            except Exception as e:
                return PumpAdvisoryDecision(
                    proposed_action="HOLD",
                    pump_id=pump_id,
                    target_pond_id=target_pond_id,
                    reason=f"Error evaluating target pond '{target_pond_id}' water status: {e}. Operation unsafe.",
                    transformer_id=tx_id,
                    transformer_headroom_kw=headroom_kw,
                    interlocks_ok=False,
                    execution_mode="DRY_RUN",
                    operator_id=operator_id,
                )
        else:
            return PumpAdvisoryDecision(
                proposed_action="HOLD",
                pump_id=pump_id,
                target_pond_id=None,
                reason="No recipient pond specified. Select target pond to evaluate water intake requirement.",
                transformer_id=tx_id,
                transformer_headroom_kw=headroom_kw,
                interlocks_ok=False,
                execution_mode="DRY_RUN",
                operator_id=operator_id,
            )

        # 5. Check continuous headroom against verified pump rating
        if pump_kw > headroom_kw or tx_status.overload_warning:
            return PumpAdvisoryDecision(
                proposed_action="HOLD",
                pump_id=pump_id,
                target_pond_id=target_pond_id,
                reason=(
                    f"Transformer '{tx_id}' continuous headroom ({headroom_kw:.1f} kW) "
                    f"insufficient for pump rating ({pump_kw:.1f} kW). Electrical overload risk."
                ),
                transformer_id=tx_id,
                transformer_headroom_kw=headroom_kw,
                interlocks_ok=False,
                execution_mode="DRY_RUN",
                operator_id=operator_id,
            )

        # Headroom is sufficient
        if not target_pond_low and target_pond_level_m is not None:
            proposed_action = "HOLD"
            reason = (
                f"Transformer '{tx_id}' headroom OK ({headroom_kw:.1f} kW), but target pond "
                f"'{target_pond_id}' water level ({target_pond_level_m:.2f}m) is already optimal."
            )
            interlocks_ok = True
        else:
            proposed_action = "START"
            reason = (
                f"Transformer '{tx_id}' headroom OK ({headroom_kw:.1f} kW available for {pump_kw:.1f} kW pump). "
                f"Target pond '{target_pond_id}' water level ({target_pond_level_m:.2f}m) below target depth. "
                f"Intake pumping recommended (DRY-RUN advisory only)."
            )
            interlocks_ok = True

        return PumpAdvisoryDecision(
            proposed_action=proposed_action,
            pump_id=pump_id,
            target_pond_id=target_pond_id,
            reason=reason,
            transformer_id=tx_id,
            transformer_headroom_kw=headroom_kw,
            interlocks_ok=interlocks_ok,
            execution_mode="DRY_RUN",
            operator_id=operator_id,
        )

    def update_pump_state(
        self,
        farm_id: str,
        pump_id: str,
        desired_state: str,
        physical_state: str,
        current_draw_amps: float = 0.0,
        power_kw: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """Record verified physical running state or dry-run desired state."""
        return self._water_repo.update_pump_state(
            farm_id=farm_id,
            pump_id=pump_id,
            desired_state=desired_state,
            physical_state=physical_state,
            current_draw_amps=current_draw_amps,
            power_kw=power_kw,
        )

    # -------------------------------------------------------------------------
    # Water Exchange Audit Logs
    # -------------------------------------------------------------------------
    def log_water_exchange(
        self,
        farm_id: str,
        pond_id: str,
        mode: str,
        initial_level_m: float,
        operator_id: str,
        final_level_m: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record manual or advisory water exchange activity."""
        # Enforce pond isolation: pond must belong to farm_id
        pond = self._pond_repo.get_by_id(farm_id=farm_id, pond_id=pond_id)
        if not pond:
            raise ValueError(f"Pond '{pond_id}' not found in farm '{farm_id}'.")

        return self._water_repo.log_water_exchange(
            farm_id=farm_id,
            pond_id=pond_id,
            mode=mode,
            initial_level_m=initial_level_m,
            operator_id=operator_id,
            final_level_m=final_level_m,
            notes=notes,
        )

    def complete_water_exchange(
        self,
        farm_id: str,
        exchange_id: str,
        final_level_m: float,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark an ongoing exchange as completed with farm isolation."""
        return self._water_repo.complete_water_exchange(
            farm_id=farm_id,
            exchange_id=exchange_id,
            final_level_m=final_level_m,
            notes=notes,
        )

    def list_water_exchange_logs(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List historical exchange and drainage records."""
        return self._water_repo.list_water_exchange_logs(farm_id=farm_id, pond_id=pond_id, limit=limit)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _record_safety_alert(
        self,
        farm_id: str,
        pond_id: str,
        alert_code: str,
        severity: str,
        message: str,
        recommended_action: str,
        trigger_value: Optional[float] = None,
        threshold_value: Optional[float] = None,
    ) -> None:
        """Create or update alert in SQL alert repository."""
        try:
            from packages.telemetry_schema.models import SeverityLevel
            try:
                sev = SeverityLevel(severity)
            except Exception:
                sev = SeverityLevel.WARNING

            self._alert_repo.raise_or_update(
                farm_id=farm_id,
                pond_id=pond_id,
                alert_code=alert_code,
                severity=sev,
                message=message,
                recommended_action=recommended_action,
            )
        except Exception as e:
            logger.warning("Could not persist alert %s: %s", alert_code, e)
