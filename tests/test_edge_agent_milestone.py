from apps.api.src.agent.decision_engine import build_decision_review
from apps.api.src.routes.agent import _decision_correlation_key
from apps.api.src.routes.edge_control import EdgeCommandRequest
from apps.api.src.routes.simulator import SIMULATION_DATASETS


def test_duplicate_issue_key_is_stable_and_scoped_to_pond_category_title():
    one = {"pond_id": "pond-01", "category": "WATER_QUALITY", "title": "Low dissolved oxygen"}
    two = {"pond_id": "pond-01", "category": "WATER_QUALITY", "title": "Low dissolved oxygen"}
    other_pond = {"pond_id": "pond-02", "category": "WATER_QUALITY", "title": "Low dissolved oxygen"}
    assert _decision_correlation_key(one) == _decision_correlation_key(two)
    assert _decision_correlation_key(one) != _decision_correlation_key(other_pond)


def test_edge_command_contract_is_only_requested_state_and_duration():
    request = EdgeCommandRequest(
        farm_id="farm-alpha", pond_id="pond-01", decision_id="12345678-1234-1234-1234-123456789012",
        actuator_type="AERATOR", actuator_id="aerator-pond-01-1", requested_state="ON",
        reason="Simulated low oxygen response", max_duration_seconds=120,
    )
    assert request.requested_state == "ON"
    assert request.max_duration_seconds == 120
    # The API implementation hard-codes DRY_RUN and never accepts a physical-enable flag.
    assert "physical_execution_enabled" not in request.model_dump()


def test_sample_scenarios_are_explicitly_synthetic_and_cover_fault_cases():
    assert {"baseline-stable", "low-do-event", "sensor-stale", "aerator-failure", "probe-fouling"}.issubset(SIMULATION_DATASETS)
    assert SIMULATION_DATASETS["low-do-event"]["scenario_type"] == "SUDDEN_HYPOXIA"


def test_decision_review_never_turns_missing_data_into_healthy_finding():
    result = build_decision_review([{"tool": "telemetry", "data_class": "UNAVAILABLE"}])
    assert result["status"] == "PARTIAL"
    assert result["finding_count"] == 0
    assert "telemetry" in result["source_tools_unavailable"]

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apps.api.src.services.edge_command_simulation import evaluate_simulated_actuator_command
from packages.telemetry_schema.models import MetricType, QualityStatus


def _packet(*, age_seconds=0, do_value=6.0, do_quality=QualityStatus.GOOD, water_level=None, simulated=True):
    now = datetime.now(timezone.utc)
    metrics = {
        MetricType.DISSOLVED_OXYGEN: SimpleNamespace(value=do_value, quality=do_quality),
    }
    if water_level is not None:
        metrics[MetricType.WATER_LEVEL] = SimpleNamespace(value=water_level, quality=QualityStatus.GOOD)
    return SimpleNamespace(timestamp=now - timedelta(seconds=age_seconds), metrics=metrics, is_simulated=simulated), now


def test_aerator_off_simulation_is_blocked_when_do_is_unsafe():
    packet, now = _packet(do_value=1.8)
    unsafe = SimpleNamespace(is_safe=False, severity=SimpleNamespace(value="EMERGENCY"))
    result = evaluate_simulated_actuator_command(
        actuator_type="AERATOR", requested_state="OFF", packet=packet,
        safety_evaluation=unsafe, now=now,
    )
    assert result["simulation_status"] == "BLOCKED_BY_SIMULATED_INTERLOCK"
    assert result["physical_command_sent"] is False


def test_stale_telemetry_blocks_command_simulation():
    packet, now = _packet(age_seconds=180)
    safe = SimpleNamespace(is_safe=True, severity=SimpleNamespace(value="NORMAL"))
    result = evaluate_simulated_actuator_command(
        actuator_type="AERATOR", requested_state="ON", packet=packet,
        safety_evaluation=safe, now=now, max_telemetry_age_seconds=120,
    )
    assert result["reason_code"] == "TELEMETRY_STALE"
    assert result["physical_state_confirmed"] is False


def test_simulated_feedback_fault_is_distinguished_from_physical_state():
    packet, now = _packet()
    safe = SimpleNamespace(is_safe=True, severity=SimpleNamespace(value="NORMAL"))
    result = evaluate_simulated_actuator_command(
        actuator_type="AERATOR", requested_state="ON", packet=packet,
        safety_evaluation=safe, feedback_profile="ACTUATOR_STUCK", now=now,
    )
    assert result["simulation_status"] == "SIMULATED_FEEDBACK_MISMATCH"
    assert result["simulated_feedback_state"] == "OFF"
    assert result["physical_command_sent"] is False
    assert result["physical_state_confirmed"] is False


def test_water_pump_on_requires_good_water_level_telemetry():
    packet, now = _packet()
    safe = SimpleNamespace(is_safe=True, severity=SimpleNamespace(value="NORMAL"))
    result = evaluate_simulated_actuator_command(
        actuator_type="WATER_PUMP", requested_state="ON", packet=packet,
        safety_evaluation=safe, now=now,
    )
    assert result["reason_code"] == "WATER_LEVEL_INTERLOCK_UNAVAILABLE"
