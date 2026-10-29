from apps.api.src.agent.decision_engine import build_decision_review


def test_decision_review_prioritizes_deduplicates_and_keeps_evidence():
    evidence = [
        {
            "tool": "farm_actions",
            "data_class": "DERIVED_ADVISORY",
            "result": {
                "actions": [
                    {
                        "action_id": "act-do-1",
                        "title": "Review pond oxygen",
                        "severity": "WARNING",
                        "pond_id": "pond-01",
                        "reason": "Configured evaluator returned warning",
                        "supporting_evidence": {"do_mg_l": 3.6},
                        "confidence": "MEASURED",
                        "recommended_next_step": "Verify current sensor reading",
                    },
                    {
                        "action_id": "act-do-1",
                        "title": "Review pond oxygen",
                        "severity": "CRITICAL",
                        "pond_id": "pond-01",
                        "reason": "Updated evaluator severity",
                        "supporting_evidence": {"do_mg_l": 2.8},
                        "confidence": "MEASURED",
                    },
                ]
            },
        },
        {"tool": "water_status", "data_class": "UNAVAILABLE", "error": "unavailable"},
    ]

    review = build_decision_review(evidence, evaluated_at="2026-10-14T00:00:00+00:00")

    assert review["status"] == "PARTIAL"
    assert review["finding_count"] == 1
    assert review["findings"][0]["severity"] == "CRITICAL"
    assert review["findings"][0]["evidence"] == {"do_mg_l": 2.8}
    assert review["source_tools_unavailable"] == ["water_status"]
    assert review["decision_policy"] == "SOURCE_BACKED_ADVISORY_ONLY"


def test_decision_review_does_not_invent_findings_when_sources_have_no_actions():
    review = build_decision_review([
        {"tool": "production_summary", "data_class": "CALCULATED_ESTIMATE", "result": {"biomass": None}}
    ])
    assert review["finding_count"] == 0
    assert review["status"] == "AVAILABLE"
    assert review["findings"] == []


from apps.api.src.agent.tool_registry import ReadOnlyFarmToolRegistry
from apps.api.src.routes.agent import _verify_outcome_against_telemetry
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from packages.telemetry_schema.models import AlertSeverity, MetricReading, MetricType, PondTelemetryPacket, QualityStatus, SafetyEvaluationResult
from datetime import datetime, timezone


def test_tool_registry_definitions_match_capabilities():
    tools = ReadOnlyFarmToolRegistry.definitions()
    tool_names = {t.name for t in tools}
    expected = {
        "farm_overview", "pond_status", "low_oxygen_risk", "telemetry_health",
        "farm_actions", "production_summary", "feed_inventory", "water_status",
        "power_status", "working_capital", "pond_health",
    }
    assert expected.issubset(tool_names)
    assert len(tools) == 11


def test_tool_registry_telemetry_tools_execution(db_session):
    registry = ReadOnlyFarmToolRegistry(db_session)
    overview = registry.run("farm_overview", farm_id="farm-alpha")
    assert overview["farm_id"] == "farm-alpha"
    assert overview["total_ponds"] == 20
    assert "status_counts" in overview

    risk = registry.run("low_oxygen_risk", farm_id="farm-alpha")
    assert risk["farm_id"] == "farm-alpha"
    assert "at_risk_count" in risk

    health = registry.run("telemetry_health", farm_id="farm-alpha")
    assert health["farm_id"] == "farm-alpha"
    assert "healthy_count" in health


def test_decision_telemetry_outcome_verification(db_session):
    repo = SQLTelemetryRepository(db_session)
    now = datetime.now(timezone.utc)

    # 1. Recovered condition: DO = 5.8
    good_packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-01",
        timestamp=now,
        metrics={
            MetricType.DISSOLVED_OXYGEN: MetricReading(metric_type=MetricType.DISSOLVED_OXYGEN, value=5.8, unit="mg/L", quality=QualityStatus.GOOD),
            MetricType.TEMPERATURE: MetricReading(metric_type=MetricType.TEMPERATURE, value=28.5, unit="°C", quality=QualityStatus.GOOD),
        },
        is_simulated=True,
    )
    good_eval = SafetyEvaluationResult(
        pond_id="pond-01",
        is_safe=True,
        severity=AlertSeverity.NORMAL,
        messages=[],
    )
    repo.save(good_packet, good_eval)

    res = _verify_outcome_against_telemetry(
        db_session, "farm-alpha", "pond-01", {"title": "Low dissolved oxygen emergency"}
    )
    assert res["verified"] is True
    assert "recovered" in res["reason"].lower()

    # 2. Unrecovered condition: DO = 2.4
    bad_packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-01",
        timestamp=now,
        metrics={
            MetricType.DISSOLVED_OXYGEN: MetricReading(metric_type=MetricType.DISSOLVED_OXYGEN, value=2.4, unit="mg/L", quality=QualityStatus.GOOD),
            MetricType.TEMPERATURE: MetricReading(metric_type=MetricType.TEMPERATURE, value=28.5, unit="°C", quality=QualityStatus.GOOD),
        },
        is_simulated=True,
    )
    bad_eval = SafetyEvaluationResult(
        pond_id="pond-01",
        is_safe=False,
        severity=AlertSeverity.CRITICAL,
        messages=["DO critical"],
    )
    repo.save(bad_packet, bad_eval)

    res2 = _verify_outcome_against_telemetry(
        db_session, "farm-alpha", "pond-01", {"title": "Low dissolved oxygen emergency"}
    )
    assert res2["verified"] is False
    assert "not yet confirmed" in res2["reason"].lower()
