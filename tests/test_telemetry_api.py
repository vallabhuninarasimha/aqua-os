"""Integration tests for FastAPI endpoints: Health, Ponds, and Telemetry."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from packages.telemetry_schema.models import (
    AlertSeverity,
    MetricReading,
    MetricType,
    PondTelemetryPacket,
)


def test_health_check_endpoint(client: TestClient):
    """Verify /health returns healthy status (public endpoint)."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_name"] == "Aqua OS API"


def test_readiness_probe_initial_state(client: TestClient):
    """Verify readiness reports baseline 20 ponds ready for ingestion."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["active_ponds"] == 20
    assert data["total_ponds"] == 20
    assert data["ingested_packets_count"] == 0


def test_unauthenticated_request_rejected(client: TestClient):
    """Verify protected endpoints reject requests lacking Bearer token."""
    response = client.get("/api/v1/ponds/summary")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_get_farm_summary(client: TestClient, operator_headers: dict):
    """Verify /api/v1/ponds/summary returns 20 ponds with valid credentials."""
    response = client.get("/api/v1/ponds/summary", headers=operator_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["active_ponds"] == 20
    assert data["total_ponds"] == 20
    assert data["telemetry_interval_seconds"] == 10


def test_list_all_ponds(client: TestClient, operator_headers: dict):
    """Verify /api/v1/ponds returns all 20 ponds."""
    response = client.get("/api/v1/ponds", headers=operator_headers)
    assert response.status_code == 200
    ponds = response.json()
    assert len(ponds) == 20
    assert ponds[0]["pond_id"] == "pond-01"
    assert ponds[19]["pond_id"] == "pond-20"


def test_get_specific_pond(client: TestClient, operator_headers: dict):
    """Verify single pond retrieval and 404 behavior."""
    response = client.get("/api/v1/ponds/pond-05", headers=operator_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["pond_id"] == "pond-05"
    assert data["aerator_count"] == 4

    missing_resp = client.get("/api/v1/ponds/pond-999", headers=operator_headers)
    assert missing_resp.status_code == 404


def test_telemetry_ingest_normal_conditions(
    client: TestClient,
    operator_headers: dict,
    sample_telemetry_packet: PondTelemetryPacket,
):
    """Verify normal telemetry produces is_safe=True and NORMAL severity."""
    payload = sample_telemetry_packet.model_dump(mode="json")
    response = client.post("/api/v1/telemetry", json=payload, headers=operator_headers)

    assert response.status_code == 202
    result = response.json()
    assert result["pond_id"] == "pond-01"
    assert result["is_safe"] is True
    assert result["severity"] == AlertSeverity.NORMAL.value
    assert result["recommended_action"] is None


def test_telemetry_ingest_emergency_hypoxia(client: TestClient, operator_headers: dict):
    """Verify DO < 3.0 mg/L immediately trips EMERGENCY alert and aeration advisory."""
    packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-03",
        timestamp=datetime.now(timezone.utc),
        metrics={
            MetricType.DISSOLVED_OXYGEN: MetricReading(
                metric_type=MetricType.DISSOLVED_OXYGEN,
                value=2.4,  # Critical hypoxia!
                unit="mg/L",
            ),
            MetricType.TEMPERATURE: MetricReading(
                metric_type=MetricType.TEMPERATURE,
                value=29.0,
                unit="°C",
            ),
        },
    )

    response = client.post(
        "/api/v1/telemetry",
        json=packet.model_dump(mode="json"),
        headers=operator_headers,
    )
    assert response.status_code == 202
    result = response.json()
    assert result["is_safe"] is False
    assert result["severity"] == AlertSeverity.EMERGENCY.value
    assert result["recommended_action"] == "ENGAGE_EMERGENCY_AERATION"
    assert any("CRITICAL HYPOXIA" in msg for msg in result["messages"])


def test_telemetry_missing_critical_do_sensor_never_safe(
    client: TestClient,
    operator_headers: dict,
):
    """CRITICAL SAFETY RULE: Missing DO sensor data must NEVER be treated as safe."""
    packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-02",
        timestamp=datetime.now(timezone.utc),
        metrics={
            MetricType.TEMPERATURE: MetricReading(
                metric_type=MetricType.TEMPERATURE,
                value=28.0,
                unit="°C",
            )
        },
    )

    response = client.post(
        "/api/v1/telemetry",
        json=packet.model_dump(mode="json"),
        headers=operator_headers,
    )
    assert response.status_code == 202
    result = response.json()
    # Missing DO must be flagged unsafe and DEGRADED!
    assert result["is_safe"] is False
    assert result["severity"] == AlertSeverity.DEGRADED.value
    assert any("CRITICAL SENSOR MISSING" in msg for msg in result["messages"])
    assert result["recommended_action"] == "INSPECT_DO_SENSOR_CONNECTIVITY"


def test_telemetry_ingest_low_do_warning(client: TestClient, operator_headers: dict):
    """Verify DO between warning and emergency threshold advises auxiliary aeration."""
    packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-04",
        timestamp=datetime.now(timezone.utc),
        metrics={
            MetricType.DISSOLVED_OXYGEN: MetricReading(
                metric_type=MetricType.DISSOLVED_OXYGEN,
                value=3.7,  # Below warning threshold (4.0) but above emergency (3.0)
                unit="mg/L",
            )
        },
    )

    response = client.post(
        "/api/v1/telemetry",
        json=packet.model_dump(mode="json"),
        headers=operator_headers,
    )
    assert response.status_code == 202
    result = response.json()
    assert result["is_safe"] is False
    assert result["severity"] == AlertSeverity.CRITICAL.value
    assert result["recommended_action"] == "START_AUXILIARY_AERATOR"


def test_telemetry_latest_and_history_persistence(
    client: TestClient,
    operator_headers: dict,
    sample_telemetry_packet: PondTelemetryPacket,
):
    """Verify that telemetry persists to database and can be queried as latest & history."""
    # Ingest packet for pond-01
    client.post(
        "/api/v1/telemetry",
        json=sample_telemetry_packet.model_dump(mode="json"),
        headers=operator_headers,
    )

    # Query latest for pond-01
    resp = client.get("/api/v1/telemetry/latest/pond-01", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pond_id"] == "pond-01"
    assert data["latest_telemetry"] is not None
    assert data["latest_safety_evaluation"]["is_safe"] is True

    # Query historical records
    hist_resp = client.get("/api/v1/telemetry/history/pond-01", headers=operator_headers)
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) >= 1
    assert history[0]["pond_id"] == "pond-01"


def test_dynamic_expansion_and_immediate_telemetry(client: TestClient, admin_headers: dict):
    """Verify adding pond-21 via API and immediately sending telemetry to it."""
    new_pond_payload = {
        "farm_id": "farm-alpha",
        "pond_id": "pond-21",
        "name": "Pond 21 Scaled",
        "area_hectares": 0.6,
        "depth_meters": 1.3,
        "species": "Litopenaeus vannamei",
        "stocking_density_per_m2": 70,
        "days_of_culture": 10,
        "is_active": True,
        "aerator_count": 4,
        "feeder_count": 1,
        "thresholds": {
            "do_emergency_mg_l": 3.0,
            "do_warning_mg_l": 4.0,
            "do_target_min_mg_l": 5.0,
            "ph_min": 7.5,
            "ph_max": 8.5,
            "temp_min_c": 26.0,
            "temp_max_c": 32.0,
            "salinity_min_ppt": 10.0,
            "salinity_max_ppt": 35.0,
        },
    }
    create_resp = client.post("/api/v1/ponds", json=new_pond_payload, headers=admin_headers)
    assert create_resp.status_code == 201

    # Ingest telemetry for pond-21
    packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-21",
        metrics={
            MetricType.DISSOLVED_OXYGEN: MetricReading(
                metric_type=MetricType.DISSOLVED_OXYGEN,
                value=6.0,
                unit="mg/L",
            )
        },
    )
    t_resp = client.post(
        "/api/v1/telemetry",
        json=packet.model_dump(mode="json"),
        headers=admin_headers,
    )
    assert t_resp.status_code == 202
    assert t_resp.json()["pond_id"] == "pond-21"
    assert t_resp.json()["is_safe"] is True
