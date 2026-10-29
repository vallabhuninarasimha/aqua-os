"""Tests for Local-First Realtime Farm Monitoring Dashboard and Simulator API."""

from fastapi.testclient import TestClient

from apps.api.src.config import settings
from apps.api.src.main import app

client = TestClient(app)


def get_operator_auth_headers() -> dict:
    """Helper to acquire valid JWT Bearer headers for default operator."""
    login_resp = client.post(
        f"{settings.api_prefix}/auth/login",
        json={"username": "operator", "password": "operator_secret_123"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_overview_unauthenticated_rejected():
    """Verify dashboard overview endpoint rejects requests without credentials."""
    resp = client.get(f"{settings.api_prefix}/dashboard/overview")
    assert resp.status_code == 401


def test_dashboard_overview_returns_20_ponds():
    """Verify dashboard overview returns summary, 20 pond cards, and biological notice."""
    headers = get_operator_auth_headers()
    # Step simulation once to populate live readings
    step_resp = client.post(f"{settings.api_prefix}/simulator/step", headers=headers)
    assert step_resp.status_code == 200

    resp = client.get(f"{settings.api_prefix}/dashboard/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["farm_id"] == "farm-alpha"
    assert "summary" in data
    assert data["summary"]["total_ponds"] == 20
    assert len(data["ponds"]) == 20

    first_pond = data["ponds"][0]
    assert first_pond["pond_id"] == "pond-01"
    assert first_pond["status"] in ("NORMAL", "WARNING", "CRITICAL", "DEGRADED", "UNKNOWN")
    assert first_pond["is_simulated"] is True
    assert "dissolved_oxygen" in first_pond["metrics"]

    assert "biological_notice" in data
    assert "Litopenaeus" in data["biological_notice"]


def test_static_dashboard_html_served():
    """Verify the root endpoint serves the local offline HTML dashboard."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "AQUA OS" in resp.text
    assert "Farm Operations Overview" in resp.text
    assert "System readiness" in resp.text


def test_simulator_status_and_step():
    """Verify simulator status query and manual 1x step advancement."""
    headers = get_operator_auth_headers()
    status_resp = client.get(f"{settings.api_prefix}/simulator/status", headers=headers)
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert "is_running" in status_data
    assert status_data["pond_count"] == 20

    step_resp = client.post(f"{settings.api_prefix}/simulator/step", headers=headers)
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["ponds_generated"] == 20


def test_simulator_scenario_injection_and_reset():
    """Verify scenario injection on specific pond and reset back to normal."""
    headers = get_operator_auth_headers()
    inject_resp = client.post(
        f"{settings.api_prefix}/simulator/scenario",
        headers=headers,
        json={
            "pond_id": "pond-03",
            "scenario_type": "AERATOR_FAILURE",
            "duration_hours": 6.0,
        },
    )
    assert inject_resp.status_code == 200
    assert "AERATOR_FAILURE" in inject_resp.json()["active_scenarios"]["pond-03"]

    reset_resp = client.post(f"{settings.api_prefix}/simulator/reset", headers=headers)
    assert reset_resp.status_code == 200
    assert len(reset_resp.json()["active_scenarios"]) == 0


def test_dashboard_stream_token_query_param_auth():
    """Verify SSE streaming endpoint accepts token in query parameter for browser EventSource."""
    # 1. Unauthenticated request must be rejected with 401
    unauth_resp = client.get(f"{settings.api_prefix}/dashboard/stream")
    assert unauth_resp.status_code == 401

    # 2. Authenticated with token query param must be accepted
    login_resp = client.post(
        f"{settings.api_prefix}/auth/login",
        json={"username": "operator", "password": "operator_secret_123"},
    )
    token = login_resp.json()["access_token"]

    with client.stream(
        "GET", f"{settings.api_prefix}/dashboard/stream?token={token}&max_events=1"
    ) as stream:
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        lines = list(stream.iter_lines())
        assert any("connected" in line for line in lines)
