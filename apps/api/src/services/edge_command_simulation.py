"""Pure simulation-only actuator command evaluator.

This module models command/interlock outcomes for test datasets. It never imports
hardware drivers and never issues physical commands.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from packages.telemetry_schema.models import MetricType, QualityStatus

SIMULATION_FEEDBACK_PROFILES = {
    "NORMAL_FEEDBACK": "Simulated actuator feedback follows the requested state.",
    "ACTUATOR_STUCK": "Simulated actuator feedback does not follow the requested state.",
    "FEEDBACK_LOST": "Simulated actuator feedback is unavailable.",
}


def evaluate_simulated_actuator_command(
    *,
    actuator_type: str,
    requested_state: str,
    packet: Any | None,
    safety_evaluation: Any | None,
    feedback_profile: str = "NORMAL_FEEDBACK",
    now: datetime | None = None,
    max_telemetry_age_seconds: int = 120,
) -> dict[str, Any]:
    """Return a transparent simulated result; never claim a physical state."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if feedback_profile not in SIMULATION_FEEDBACK_PROFILES:
        raise ValueError("Unsupported simulated feedback profile")

    if packet is None:
        return _blocked("TELEMETRY_UNAVAILABLE", "No telemetry is available for the pond.")

    timestamp = packet.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (now - timestamp).total_seconds())
    if age_seconds > max_telemetry_age_seconds:
        return _blocked(
            "TELEMETRY_STALE",
            f"Latest telemetry is {age_seconds:.1f}s old; maximum allowed for this simulation is {max_telemetry_age_seconds}s.",
            telemetry_age_seconds=round(age_seconds, 1),
            telemetry_timestamp=timestamp.isoformat(),
            telemetry_is_simulated=bool(getattr(packet, "is_simulated", False)),
        )

    metrics = getattr(packet, "metrics", {}) or {}
    if actuator_type == "AERATOR" and requested_state == "OFF":
        do_reading = metrics.get(MetricType.DISSOLVED_OXYGEN)
        if do_reading is None or do_reading.quality not in (QualityStatus.GOOD,):
            return _blocked(
                "DO_QUALITY_INSUFFICIENT",
                "Aerator OFF simulation is blocked because dissolved-oxygen telemetry is missing or not marked GOOD.",
                telemetry_age_seconds=round(age_seconds, 1),
                telemetry_is_simulated=bool(getattr(packet, "is_simulated", False)),
            )
        if safety_evaluation is None or not bool(getattr(safety_evaluation, "is_safe", False)):
            return _blocked(
                "BIOLOGICAL_SAFETY_NOT_CONFIRMED",
                "Aerator OFF simulation is blocked because current safety evaluation is absent or unsafe.",
                telemetry_age_seconds=round(age_seconds, 1),
                telemetry_is_simulated=bool(getattr(packet, "is_simulated", False)),
                safety_severity=getattr(getattr(safety_evaluation, "severity", None), "value", None),
            )

    if actuator_type == "WATER_PUMP" and requested_state == "ON":
        level_reading = metrics.get(MetricType.WATER_LEVEL)
        if level_reading is None or level_reading.quality not in (QualityStatus.GOOD,):
            return _blocked(
                "WATER_LEVEL_INTERLOCK_UNAVAILABLE",
                "Water-pump ON simulation is blocked because a GOOD water-level reading is unavailable.",
                telemetry_age_seconds=round(age_seconds, 1),
                telemetry_is_simulated=bool(getattr(packet, "is_simulated", False)),
            )

    common = {
        "telemetry_timestamp": timestamp.isoformat(),
        "telemetry_age_seconds": round(age_seconds, 1),
        "telemetry_is_simulated": bool(getattr(packet, "is_simulated", False)),
        "safety_evaluation_present": safety_evaluation is not None,
        "physical_command_sent": False,
        "physical_state_confirmed": False,
        "simulation_only": True,
    }
    if feedback_profile == "FEEDBACK_LOST":
        return {
            **common,
            "simulation_status": "SIMULATED_FEEDBACK_UNKNOWN",
            "simulated_feedback_state": "UNKNOWN",
            "reason_code": "SIMULATED_FEEDBACK_LOST",
            "message": SIMULATION_FEEDBACK_PROFILES[feedback_profile],
        }
    if feedback_profile == "ACTUATOR_STUCK":
        simulated_feedback = "OFF" if requested_state == "ON" else "ON"
        return {
            **common,
            "simulation_status": "SIMULATED_FEEDBACK_MISMATCH",
            "simulated_feedback_state": simulated_feedback,
            "reason_code": "SIMULATED_ACTUATOR_STUCK",
            "message": SIMULATION_FEEDBACK_PROFILES[feedback_profile],
        }
    return {
        **common,
        "simulation_status": "SIMULATED_FEEDBACK_MATCH",
        "simulated_feedback_state": requested_state,
        "reason_code": "SIMULATED_NORMAL_FEEDBACK",
        "message": SIMULATION_FEEDBACK_PROFILES[feedback_profile],
    }


def _blocked(reason_code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "simulation_status": "BLOCKED_BY_SIMULATED_INTERLOCK",
        "simulated_feedback_state": "UNKNOWN",
        "reason_code": reason_code,
        "message": message,
        "physical_command_sent": False,
        "physical_state_confirmed": False,
        "simulation_only": True,
        **details,
    }
