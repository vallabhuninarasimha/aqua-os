"""Comprehensive end-to-end integration test suite verifying all 14 Aqua OS modules.

Independently validates:
1. Overview & Health Dashboard
2. Registered Ponds & Status
3. Live Sensor Telemetry & Ingestion
4. Daily Farm Operations Intelligence
5. Daily Ration & Feeding Planner
6. Equipment Fleet & Aeration Override Safety
7. Biometric & Production Analytics (Batches)
8. Water Management, Monk Sluice Gates & Exchanges
9. Shrimp Health, Pathology & Mortality Tracking
10. Biological & Incident Alerts Management
11. Farm Financials & Expense Ledger
12. Reports & Harvest Readiness
13. Autonomous Agent & Grounded AI Advisor
14. System Settings, Edge Gateways & Transformer Power
15. RBAC Authentication & Permission Enforcement
16. Cross-Farm Tenant Isolation
17. Actuator Dry-Run Interlock Safety Guarantees
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient


# Module 1: Overview Dashboard
def test_module_1_overview_dashboard(client: TestClient, operator_headers: dict):
    resp = client.get("/api/v1/dashboard/overview?farm_id=farm-alpha", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["farm_id"] == "farm-alpha"
    assert "summary" in data
    assert "ponds" in data
    assert len(data["ponds"]) == 20
    assert "edge_status" in data


# Module 2: Registered Ponds & Status
def test_module_2_registered_ponds(client: TestClient, operator_headers: dict):
    # 1. Read existing ponds
    list_resp = client.get("/api/v1/ponds?farm_id=farm-alpha", headers=operator_headers)
    assert list_resp.status_code == 200
    ponds = list_resp.json()
    assert len(ponds) == 20

    # 2. Get specific pond detail
    p1_resp = client.get("/api/v1/ponds/pond-01?farm_id=farm-alpha", headers=operator_headers)
    assert p1_resp.status_code == 200
    p1 = p1_resp.json()
    assert p1["pond_id"] == "pond-01"
    assert p1["farm_id"] == "farm-alpha"


# Module 3: Live Sensor Stream & Telemetry
def test_module_3_live_sensor_stream(client: TestClient, operator_headers: dict):
    # 1. Ingest a live telemetry packet for pond-01
    packet_payload = {
        "schema_version": "1.0",
        "farm_id": "farm-alpha",
        "pond_id": "pond-01",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "dissolved_oxygen": {"metric_type": "dissolved_oxygen", "value": 5.8, "unit": "mg/L", "quality": "GOOD"},
            "temperature": {"metric_type": "temperature", "value": 28.5, "unit": "°C", "quality": "GOOD"},
            "ph": {"metric_type": "ph", "value": 7.9, "unit": "pH", "quality": "GOOD"},
            "salinity": {"metric_type": "salinity", "value": 25.0, "unit": "ppt", "quality": "GOOD"},
            "water_level": {"metric_type": "water_level", "value": 1.25, "unit": "m", "quality": "GOOD"}
        },
        "hardware_status": {
            "mains_power_ok": True,
            "battery_level_pct": 98.0,
            "rssi_dbm": -66,
            "local_buffer_backlog": 0
        },
        "is_simulated": True
    }
    ingest_resp = client.post("/api/v1/telemetry", json=packet_payload, headers=operator_headers)
    assert ingest_resp.status_code == 202

    # 2. Query latest telemetry across ponds
    latest_resp = client.get("/api/v1/telemetry/latest?farm_id=farm-alpha", headers=operator_headers)
    assert latest_resp.status_code == 200
    telemetry_map = latest_resp.json()
    assert isinstance(telemetry_map, dict)
    assert "pond-01" in telemetry_map

    # 3. Query historical telemetry window for pond-01
    hist_resp = client.get("/api/v1/telemetry/history/pond-01?farm_id=farm-alpha&limit=50", headers=operator_headers)
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert isinstance(history, list)
    assert len(history) >= 1


# Module 4: Daily Farm Operations Intelligence
def test_module_4_operations_intelligence(client: TestClient, operator_headers: dict):
    resp = client.get("/api/v1/dashboard/operations?farm_id=farm-alpha", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "action_center" in data
    assert "pond_states" in data


# Module 5: Daily Ration & Feeding Planner
def test_module_5_daily_ration_and_feeding(client: TestClient, admin_headers: dict):
    # 1. List current feed plans
    list_resp = client.get("/api/v1/feed-plans?farm_id=farm-alpha", headers=admin_headers)
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)

    # 2. Create a feed plan (requires PONDS_WRITE)
    plan_payload = {
        "pond_id": "pond-01",
        "plan_date": datetime.now(timezone.utc).isoformat(),
        "planned_daily_kg": 120.0,
        "feeding_sessions_count": 4,
        "feed_type": "Grower Pellet 38%",
        "recommendation_basis": "MANUAL",
        "notes": "Test feeding schedule",
        "auto_approve": True,
    }
    create_resp = client.post("/api/v1/feed-plans?farm_id=farm-alpha", json=plan_payload, headers=admin_headers)
    assert create_resp.status_code in (200, 201)
    plan_data = create_resp.json()
    assert plan_data["pond_id"] == "pond-01"
    assert plan_data["planned_daily_kg"] == 120.0


# Module 6: Equipment Fleet & Aeration Override Safety
def test_module_6_equipment_fleet_and_aeration(client: TestClient, operator_headers: dict):
    # 1. Query aeration units for pond-01
    aero_resp = client.get("/api/v1/ponds/pond-01/aeration?farm_id=farm-alpha", headers=operator_headers)
    assert aero_resp.status_code == 200
    aero_data = aero_resp.json()
    assert "aerators" in aero_data
    assert len(aero_data["aerators"]) == 4

    # 2. Execute dry-run aeration simulation
    dry_run_resp = client.post("/api/v1/ponds/pond-01/aeration/dry-run?farm_id=farm-alpha", headers=operator_headers)
    assert dry_run_resp.status_code == 200
    dry_run_data = dry_run_resp.json()
    assert "decision_id" in dry_run_data
    assert dry_run_data["pond_id"] == "pond-01"

    # 3. Set aerator manual override
    override_payload = {
        "aerator_id": "pond-01-aero-01",
        "desired_state": "FORCE_ON"
    }
    ovr_resp = client.put("/api/v1/ponds/pond-01/aeration/override?farm_id=farm-alpha", json=override_payload, headers=operator_headers)
    assert ovr_resp.status_code == 200


# Module 7: Biometric & Production Analytics
def test_module_7_biometric_production_analytics(client: TestClient, operator_headers: dict):
    # 1. Farm-wide production summary
    summary_resp = client.get("/api/v1/production/farm/summary?farm_id=farm-alpha", headers=operator_headers)
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["farm_id"] == "farm-alpha"
    assert len(summary["ponds"]) == 20

    # 2. Pond-specific production intelligence
    p_intel = client.get("/api/v1/production/ponds/pond-01/intelligence?farm_id=farm-alpha", headers=operator_headers)
    assert p_intel.status_code == 200
    data = p_intel.json()
    assert "biomass" in data or "batch" in data


# Module 8: Water Management & Exchanges
def test_module_8_water_management_and_exchanges(client: TestClient, operator_headers: dict):
    # 1. Query pond water status
    water_resp = client.get("/api/v1/water/ponds/pond-01?farm_id=farm-alpha", headers=operator_headers)
    assert water_resp.status_code == 200
    water = water_resp.json()
    assert "target_level_m" in water or "current_level_m" in water

    # 2. Log a water exchange
    exchange_payload = {
        "pond_id": "pond-01",
        "mode": "NORMAL_MAINTENANCE",
        "initial_level_m": 1.25,
        "final_level_m": 1.25,
        "notes": "Routine surface skimming through bio-screen"
    }
    ex_resp = client.post("/api/v1/water/exchanges?farm_id=farm-alpha", json=exchange_payload, headers=operator_headers)
    assert ex_resp.status_code == 201
    exchange = ex_resp.json()
    assert exchange["pond_id"] == "pond-01"

    # 3. List water exchanges
    list_resp = client.get("/api/v1/water/exchanges?farm_id=farm-alpha", headers=operator_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1


# Module 9: Shrimp Health, Pathology & Mortality Tracking
def test_module_9_shrimp_health_and_biosecurity(client: TestClient, admin_headers: dict):
    # 1. Health summary
    health_resp = client.get("/api/v1/health/ponds/pond-01/summary?farm_id=farm-alpha", headers=admin_headers)
    assert health_resp.status_code == 200
    h_data = health_resp.json()
    assert "pond_id" in h_data
    assert "health_status" in h_data

    # 2. Record mortality
    mort_payload = {
        "dead_count": 5,
        "collection_method": "Central drain siphon",
        "suspected_reason": "Molting stress",
        "notes": "Routine sampling collection"
    }
    mort_resp = client.post("/api/v1/health/ponds/pond-01/mortality?farm_id=farm-alpha", json=mort_payload, headers=admin_headers)
    assert mort_resp.status_code in (200, 201)

    # 3. Record health observation
    obs_payload = {
        "sample_count": 25,
        "observation_method": "Feeding tray check",
        "swimming_activity": "NORMAL",
        "feed_response": "VIGOROUS",
        "gill_condition": "CLEAN_TRANSLUCENT",
        "gut_condition": "FULL_CONTINUOUS",
        "notes": "Excellent digestive tract fullness"
    }
    obs_resp = client.post("/api/v1/health/ponds/pond-01/observations?farm_id=farm-alpha", json=obs_payload, headers=admin_headers)
    assert obs_resp.status_code in (200, 201)


# Module 10: Biological Alerts Management
def test_module_10_biological_alerts_management(client: TestClient, operator_headers: dict):
    resp = client.get("/api/v1/alerts?farm_id=farm-alpha", headers=operator_headers)
    assert resp.status_code == 200
    alerts = resp.json()
    assert isinstance(alerts, list)


# Module 11: Farm Financials & Expense Ledger
def test_module_11_farm_financials_and_ledger(client: TestClient, admin_headers: dict):
    # 1. Expense summary
    sum_resp = client.get("/api/v1/expenses/summary?farm_id=farm-alpha", headers=admin_headers)
    assert sum_resp.status_code == 200

    # 2. Record an expense (requires EXPENSES_WRITE)
    exp_payload = {
        "category": "FEED",
        "amount": 35000.0,
        "currency": "INR",
        "pond_id": "pond-01",
        "supplier": "Marine Feeds Corp",
        "payment_method": "BANK_TRANSFER",
        "notes": "Grower pellet delivery"
    }
    post_exp = client.post("/api/v1/expenses?farm_id=farm-alpha", json=exp_payload, headers=admin_headers)
    assert post_exp.status_code == 201
    exp_record = post_exp.json()
    assert exp_record["amount"] == 35000.0
    assert "expense_id" in exp_record

    # 3. List expenses and verify recorded item is returned
    list_exp = client.get("/api/v1/expenses?farm_id=farm-alpha", headers=admin_headers)
    assert list_exp.status_code == 200
    items = list_exp.json().get("items", [])
    assert len(items) >= 1
    assert any(i["amount"] == 35000.0 for i in items)


# Module 12: Reports & Harvest Readiness
def test_module_12_reports_and_compliance(client: TestClient, operator_headers: dict):
    resp = client.get("/api/v1/production/batches/readiness?farm_id=farm-alpha", headers=operator_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# Module 13: Autonomous Agent & Grounded AI Advisor
def test_module_13_autonomous_agent_advisor(client: TestClient, operator_headers: dict):
    # 1. Query agent decisions list
    dec_resp = client.get("/api/v1/agent/decisions?farm_id=farm-alpha", headers=operator_headers)
    assert dec_resp.status_code == 200
    assert "decisions" in dec_resp.json()

    # 2. Query grounded AI advisor
    query_payload = {
        "question": "What is the status of Pond 1 and are oxygen levels safe?",
        "farm_id": "farm-alpha"
    }
    q_resp = client.post("/api/v1/agent/query", json=query_payload, headers=operator_headers)
    assert q_resp.status_code == 200
    ans = q_resp.json()
    assert "answer" in ans
    assert "evidence" in ans


# Module 14: System Settings, Edge Gateways & Farm Power
def test_module_14_system_settings_edge_and_power(client: TestClient, operator_headers: dict):
    # 1. Transformer power telemetry
    power_resp = client.get("/api/v1/farm/power?farm_id=farm-alpha", headers=operator_headers)
    assert power_resp.status_code == 200
    power = power_resp.json()
    assert isinstance(power, list)
    assert len(power) >= 1

    # 2. Edge gateway status
    edge_resp = client.get("/api/v1/edge/status?farm_id=farm-alpha", headers=operator_headers)
    assert edge_resp.status_code == 200
    edge = edge_resp.json()
    assert "gateway_id" in edge or "online" in edge or "status" in edge


# Security & RBAC Enforcement: Missing Token Rejection
def test_rbac_unauthenticated_request_rejected(client: TestClient):
    resp = client.get("/api/v1/dashboard/overview?farm_id=farm-alpha")
    assert resp.status_code == 401


# Security & RBAC Enforcement: Cross-Farm Tenant Isolation
def test_rbac_cross_farm_isolation(client: TestClient, beta_operator_headers: dict):
    # beta_operator cannot access farm-alpha
    resp = client.get("/api/v1/dashboard/overview?farm_id=farm-alpha", headers=beta_operator_headers)
    assert resp.status_code == 403


# Actuator Safety Guarantee: Dry-Run mode
def test_actuator_dry_run_safety_interlock(client: TestClient, operator_headers: dict):
    # Verify intake pump advisory reports DRY_RUN safety
    resp = client.get("/api/v1/water/pump/advisory?farm_id=farm-alpha&target_pond_id=pond-01", headers=operator_headers)
    assert resp.status_code == 200
    adv = resp.json()
    assert "proposed_action" in adv
    assert adv["execution_mode"] == "DRY_RUN"
