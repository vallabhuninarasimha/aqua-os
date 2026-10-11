"""Deterministic Biological Safety Rules Engine for Aqua OS.

Encapsulates threshold evaluations, missing/stale sensor guardrails,
and advisory recommendations strictly separated from API and persistence layers.
"""

from datetime import datetime, timezone
from typing import List, Optional

from packages.telemetry_schema.config import PondConfig
from packages.telemetry_schema.models import (
    AlertSeverity,
    MetricType,
    PondTelemetryPacket,
    QualityStatus,
    SafetyEvaluationResult,
)


class ThresholdSafetyEvaluator:
    """Evaluates telemetry packets against biological thresholds and sensor health.

    Guiding Rule: Missing, faulted, or out-of-bounds critical telemetry (Dissolved Oxygen)
    must NEVER be silently treated as safe.
    """

    def evaluate(
        self,
        packet: PondTelemetryPacket,
        pond_config: Optional[PondConfig],
    ) -> SafetyEvaluationResult:
        messages: List[str] = []
        severity = AlertSeverity.NORMAL
        recommended_action: Optional[str] = None

        # 1. Unregistered Pond Guardrail
        if not pond_config:
            return SafetyEvaluationResult(
                pond_id=packet.pond_id,
                is_safe=False,
                severity=AlertSeverity.UNKNOWN,
                messages=[
                    f"Pond '{packet.pond_id}' not found in active registry "
                    f"for farm '{packet.farm_id}'."
                ],
                recommended_action="REGISTER_POND_CONFIGURATION",
                evaluated_at=datetime.now(timezone.utc),
            )

        thresholds = pond_config.thresholds

        # 2. Critical Sensor Guardrail: Dissolved Oxygen (DO)
        # In shrimp aquaculture, DO depletion is fatal within 30-45 minutes.
        do_reading = packet.metrics.get(MetricType.DISSOLVED_OXYGEN)

        if do_reading is None:
            # Critical sensor completely missing
            severity = AlertSeverity.DEGRADED
            messages.append(
                "CRITICAL SENSOR MISSING: Dissolved Oxygen telemetry is unavailable. "
                "System cannot verify pond safety."
            )
            recommended_action = "INSPECT_DO_SENSOR_CONNECTIVITY"
        elif do_reading.quality == QualityStatus.SENSOR_FAULT:
            severity = AlertSeverity.CRITICAL
            messages.append(
                "CRITICAL SENSOR FAULT: Dissolved Oxygen probe reports hardware fault. "
                "Defaulting safety posture to aerators ON."
            )
            recommended_action = "VERIFY_SENSOR_AND_DEFAULT_AERATION_ON"
        elif do_reading.quality == QualityStatus.OUT_OF_BOUNDS:
            severity = AlertSeverity.CRITICAL
            messages.append(
                f"CRITICAL SENSOR OUT_OF_BOUNDS: DO reading {do_reading.value} {do_reading.unit} "
                "violates physical limits. Suspect probe disconnection or biofouling."
            )
            recommended_action = "CLEAN_OR_CALIBRATE_DO_PROBE"
        else:
            # DO is present and valid; evaluate biological thresholds
            do_val = do_reading.value
            if do_val < thresholds.do_emergency_mg_l:
                severity = AlertSeverity.EMERGENCY
                messages.append(
                    f"CRITICAL HYPOXIA: DO is {do_val:.2f} mg/L, below emergency threshold "
                    f"({thresholds.do_emergency_mg_l:.1f} mg/L)."
                )
                recommended_action = "ENGAGE_EMERGENCY_AERATION"
            elif do_val < thresholds.do_warning_mg_l:
                severity = AlertSeverity.CRITICAL
                messages.append(
                    f"LOW DO WARNING: DO is {do_val:.2f} mg/L, below warning threshold "
                    f"({thresholds.do_warning_mg_l:.1f} mg/L)."
                )
                recommended_action = "START_AUXILIARY_AERATOR"

        # 3. Secondary Parameter Checks (pH)
        ph_reading = packet.metrics.get(MetricType.PH)
        if ph_reading and ph_reading.quality in (QualityStatus.GOOD, QualityStatus.SUSPECT_DRIFT):
            ph_val = ph_reading.value
            if ph_val < thresholds.ph_min:
                if severity in (AlertSeverity.NORMAL, AlertSeverity.INFO):
                    severity = AlertSeverity.WARNING
                messages.append(
                    f"LOW pH: {ph_val:.2f} is below minimum optimal ({thresholds.ph_min:.1f})."
                )
            elif ph_val > thresholds.ph_max:
                if severity in (AlertSeverity.NORMAL, AlertSeverity.INFO):
                    severity = AlertSeverity.WARNING
                messages.append(
                    f"HIGH pH: {ph_val:.2f} exceeds maximum optimal ({thresholds.ph_max:.1f})."
                )

        # 4. Secondary Parameter Checks (Temperature)
        temp_reading = packet.metrics.get(MetricType.TEMPERATURE)
        if temp_reading and temp_reading.quality in (
            QualityStatus.GOOD,
            QualityStatus.SUSPECT_DRIFT,
        ):
            temp_val = temp_reading.value
            if temp_val < thresholds.temp_min_c:
                if severity == AlertSeverity.NORMAL:
                    severity = AlertSeverity.INFO
                messages.append(
                    f"Sub-optimal water temp: {temp_val:.1f}°C below min "
                    f"({thresholds.temp_min_c:.1f}°C)."
                )
            elif temp_val > thresholds.temp_max_c:
                if severity in (AlertSeverity.NORMAL, AlertSeverity.INFO):
                    severity = AlertSeverity.WARNING
                messages.append(
                    f"High water temp: {temp_val:.1f}°C exceeds max "
                    f"({thresholds.temp_max_c:.1f}°C)."
                )

        # 5. Non-Critical Sensor Quality Warnings
        for m_type, reading in packet.metrics.items():
            if m_type == MetricType.DISSOLVED_OXYGEN:
                continue  # Handled above
            if reading.quality == QualityStatus.OUT_OF_BOUNDS:
                if severity == AlertSeverity.NORMAL:
                    severity = AlertSeverity.WARNING
                messages.append(
                    f"Sensor {m_type.value} reading {reading.value} {reading.unit} "
                    f"is OUT_OF_BOUNDS."
                )
            elif reading.quality == QualityStatus.SUSPECT_DRIFT:
                messages.append(f"Sensor {m_type.value} shows potential drift or fouling.")

        is_safe = severity in (AlertSeverity.NORMAL, AlertSeverity.INFO)
        if not messages:
            messages.append("All measured parameters are within optimal biological ranges.")

        return SafetyEvaluationResult(
            pond_id=packet.pond_id,
            is_safe=is_safe,
            severity=severity,
            messages=messages,
            recommended_action=recommended_action,
            evaluated_at=datetime.now(timezone.utc),
        )
