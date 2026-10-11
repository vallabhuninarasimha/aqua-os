"""Telemetry Ingestion & Safety Evaluation Service.

Receives sensor telemetry packets, performs biological threshold checks,
caches current states for real-time dashboards, and generates safety alerts.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from packages.telemetry_schema.models import (
    AlertSeverity,
    MetricType,
    PondTelemetryPacket,
    QualityStatus,
    SafetyEvaluationResult,
)

from .pond_registry import pond_registry


class TelemetryService:
    """Manages telemetry ingestion, safety evaluation, and live cache."""

    def __init__(self) -> None:
        # Latest telemetry packet per pond: pond_id -> PondTelemetryPacket
        self._latest_telemetry: Dict[str, PondTelemetryPacket] = {}
        # Latest safety evaluation per pond: pond_id -> SafetyEvaluationResult
        self._latest_evaluations: Dict[str, SafetyEvaluationResult] = {}
        # Ingestion counter
        self._total_ingested_packets: int = 0

    @property
    def total_ingested_packets(self) -> int:
        return self._total_ingested_packets

    def ingest_packet(self, packet: PondTelemetryPacket) -> SafetyEvaluationResult:
        """Process and validate a single telemetry packet."""
        self._latest_telemetry[packet.pond_id] = packet
        self._total_ingested_packets += 1

        evaluation = self.evaluate_safety(packet)
        self._latest_evaluations[packet.pond_id] = evaluation
        return evaluation

    def evaluate_safety(self, packet: PondTelemetryPacket) -> SafetyEvaluationResult:
        """Evaluate water quality parameters against the target pond's configured thresholds."""
        pond_config = pond_registry.get_pond(packet.pond_id)
        messages: List[str] = []
        severity = AlertSeverity.NORMAL
        recommended_action: Optional[str] = None

        if not pond_config:
            return SafetyEvaluationResult(
                pond_id=packet.pond_id,
                is_safe=False,
                severity=AlertSeverity.WARNING,
                messages=[f"Pond '{packet.pond_id}' not found in active registry."],
                recommended_action="REGISTER_POND",
            )

        thresholds = pond_config.thresholds

        # 1. Dissolved Oxygen (DO) Evaluation (Most Critical Parameter)
        do_val = packet.get_metric_value(MetricType.DISSOLVED_OXYGEN)
        if do_val is not None:
            if do_val < thresholds.do_emergency_mg_l:
                severity = AlertSeverity.EMERGENCY
                messages.append(
                    f"CRITICAL HYPOXIA: DO is {do_val:.2f} mg/L, below emergency threshold "
                    f"({thresholds.do_emergency_mg_l:.1f} mg/L)."
                )
                recommended_action = "ENGAGE_EMERGENCY_AERATION"
            elif do_val < thresholds.do_warning_mg_l:
                if severity != AlertSeverity.EMERGENCY:
                    severity = AlertSeverity.CRITICAL
                messages.append(
                    f"LOW DO WARNING: DO is {do_val:.2f} mg/L, below warning threshold "
                    f"({thresholds.do_warning_mg_l:.1f} mg/L)."
                )
                if not recommended_action:
                    recommended_action = "START_AUXILIARY_AERATOR"

        # 2. pH Evaluation
        ph_val = packet.get_metric_value(MetricType.PH)
        if ph_val is not None:
            if ph_val < thresholds.ph_min:
                if severity == AlertSeverity.NORMAL:
                    severity = AlertSeverity.WARNING
                messages.append(
                    f"LOW pH: {ph_val:.2f} is below minimum optimal ({thresholds.ph_min:.1f})."
                )
            elif ph_val > thresholds.ph_max:
                if severity == AlertSeverity.NORMAL:
                    severity = AlertSeverity.WARNING
                messages.append(
                    f"HIGH pH: {ph_val:.2f} exceeds maximum optimal ({thresholds.ph_max:.1f})."
                )

        # 3. Temperature Evaluation
        temp_val = packet.get_metric_value(MetricType.TEMPERATURE)
        if temp_val is not None:
            if temp_val < thresholds.temp_min_c:
                if severity == AlertSeverity.NORMAL:
                    severity = AlertSeverity.INFO
                messages.append(
                    f"Sub-optimal water temp: {temp_val:.1f}°C below min "
                    f"({thresholds.temp_min_c:.1f}°C)."
                )
            elif temp_val > thresholds.temp_max_c:
                if severity == AlertSeverity.NORMAL:
                    severity = AlertSeverity.WARNING
                messages.append(
                    f"High water temp: {temp_val:.1f}°C exceeds max "
                    f"({thresholds.temp_max_c:.1f}°C)."
                )

        # 4. Sensor Quality Check
        for m_type, reading in packet.metrics.items():
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

    def get_latest_telemetry(self, pond_id: str) -> Optional[PondTelemetryPacket]:
        return self._latest_telemetry.get(pond_id)

    def get_all_latest_telemetry(self) -> Dict[str, PondTelemetryPacket]:
        return dict(self._latest_telemetry)

    def get_latest_evaluation(self, pond_id: str) -> Optional[SafetyEvaluationResult]:
        return self._latest_evaluations.get(pond_id)


# Singleton instance
telemetry_service = TelemetryService()
