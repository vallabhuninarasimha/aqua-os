"""Unit tests for telemetry, actuator, and heartbeat schemas."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.telemetry_schema.models import (
    ActuatorCommand,
    ActuatorState,
    ActuatorType,
    AlertSeverity,
    EdgeHeartbeat,
    MetricReading,
    MetricType,
    PondTelemetryPacket,
    QualityStatus,
)


def test_metric_reading_valid():
    """Verify valid sensor metric creation and field immutability."""
    reading = MetricReading(
        metric_type=MetricType.DISSOLVED_OXYGEN,
        value=6.2,
        unit="mg/L",
        quality=QualityStatus.GOOD,
    )
    assert reading.metric_type == MetricType.DISSOLVED_OXYGEN
    assert reading.value == 6.2
    assert reading.unit == "mg/L"
    assert reading.quality == QualityStatus.GOOD


def test_metric_reading_auto_flags_out_of_bounds():
    """Verify out-of-physical-bounds readings are automatically flagged."""
    reading = MetricReading(
        metric_type=MetricType.DISSOLVED_OXYGEN,
        value=35.0,  # Physical bounds for DO are 0.0 - 25.0 mg/L
        unit="mg/L",
        quality=QualityStatus.GOOD,
    )
    assert reading.quality == QualityStatus.OUT_OF_BOUNDS


def test_metric_reading_forbids_extra_fields():
    """Verify extra unexpected keys are rejected to prevent contract drift."""
    with pytest.raises(ValidationError):
        MetricReading(
            metric_type=MetricType.TEMPERATURE,
            value=29.0,
            unit="°C",
            unexpected_field="hack",  # type: ignore
        )


def test_pond_telemetry_packet_utc_enforcement():
    """Verify non-timezone-aware timestamps are normalized to UTC."""
    naive_dt = datetime(2026, 10, 10, 12, 0, 0)
    packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-05",
        timestamp=naive_dt,
        metrics={
            MetricType.TEMPERATURE: MetricReading(
                metric_type=MetricType.TEMPERATURE,
                value=28.0,
                unit="°C",
            )
        },
    )
    assert packet.timestamp.tzinfo is not None
    assert packet.timestamp.tzinfo == timezone.utc


def test_pond_telemetry_packet_empty_metrics_rejected():
    """Verify packets with empty metrics are rejected."""
    with pytest.raises(ValidationError):
        PondTelemetryPacket(
            farm_id="farm-alpha",
            pond_id="pond-01",
            metrics={},
        )


def test_actuator_command_duration_bounds():
    """Verify safety limits on actuator duration to prevent motor burnout."""
    # Duration = 0 is invalid
    with pytest.raises(ValidationError):
        ActuatorCommand(
            command_id="cmd-1",
            farm_id="farm-alpha",
            pond_id="pond-01",
            actuator_id="aerator-1",
            actuator_type=ActuatorType.AERATOR_PADDLEWHEEL,
            target_state=ActuatorState.ON,
            max_duration_seconds=0,
            reason="Testing",
            issued_by="operator-1",
        )

    # Duration > 8 hours (28800s) is invalid
    with pytest.raises(ValidationError):
        ActuatorCommand(
            command_id="cmd-2",
            farm_id="farm-alpha",
            pond_id="pond-01",
            actuator_id="aerator-1",
            actuator_type=ActuatorType.AERATOR_PADDLEWHEEL,
            target_state=ActuatorState.ON,
            max_duration_seconds=30000,
            reason="Testing",
            issued_by="operator-1",
        )


def test_edge_heartbeat_valid():
    """Verify edge gateway heartbeat validation."""
    hb = EdgeHeartbeat(
        farm_id="farm-alpha",
        gateway_id="gw-01",
        uptime_seconds=3600,
        firmware_version="1.0.4",
        active_ponds_reporting=[f"pond-{i:02d}" for i in range(1, 21)],
        offline_backlog_count=0,
    )
    assert hb.uptime_seconds == 3600
    assert len(hb.active_ponds_reporting) == 20


def test_alert_severity_states_include_degraded_and_unknown():
    """Verify presence of DEGRADED and UNKNOWN states for missing/faulted sensors."""
    assert AlertSeverity.DEGRADED.value == "DEGRADED"
    assert AlertSeverity.UNKNOWN.value == "UNKNOWN"
