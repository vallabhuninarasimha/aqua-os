import urllib.request
import json

BASE = "http://127.0.0.1:8001/api/v1"

def test_api():
    # 1. Health
    req_health = urllib.request.urlopen("http://127.0.0.1:8001/health")
    assert req_health.status == 200, "Health check failed"
    print("[OK] /health passed")

    # 2. Login as admin
    login_req = urllib.request.Request(
        f"{BASE}/auth/login",
        data=json.dumps({"username": "admin", "password": "admin_secret_123"}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(login_req) as r:
        admin_data = json.loads(r.read().decode())
        admin_token = admin_data["access_token"]
    print("[OK] Login as admin passed")

    # 3. Query farm-alpha overview
    req_alpha = urllib.request.Request(
        f"{BASE}/dashboard/overview?farm_id=farm-alpha",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    with urllib.request.urlopen(req_alpha) as r:
        alpha_data = json.loads(r.read().decode())
        assert len(alpha_data["ponds"]) == 20, "Expected 20 ponds for farm-alpha"
    print(f"[OK] farm-alpha overview returned {len(alpha_data['ponds'])} ponds")

    # 4. Query farm-beta overview
    req_beta = urllib.request.Request(
        f"{BASE}/dashboard/overview?farm_id=farm-beta",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    with urllib.request.urlopen(req_beta) as r:
        beta_data = json.loads(r.read().decode())
        assert len(beta_data["ponds"]) == 4, "Expected 4 nursery tanks for farm-beta"
    print(f"[OK] farm-beta overview returned {len(beta_data['ponds'])} tanks: {[p['pond_id'] for p in beta_data['ponds']]}")

    # 5. Verify DRY_RUN safety on actuator dry-run endpoint
    dry_req = urllib.request.Request(
        f"{BASE}/ponds/pond-01/aeration/dry-run?farm_id=farm-alpha",
        data=b"{}",
        headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(dry_req) as r:
        dry_res = json.loads(r.read().decode())
        assert dry_res.get("execution_mode") == "DRY_RUN", "DRY_RUN execution mode must be enforced"
    print("[OK] DRY_RUN actuator safety evaluation passed (execution_mode: DRY_RUN)")

    # 6. Verify cross-tenant isolation enforcement
    login_op = urllib.request.Request(
        f"{BASE}/auth/login",
        data=json.dumps({"username": "operator", "password": "operator_secret_123"}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(login_op) as r:
        op_data = json.loads(r.read().decode())
        op_token = op_data["access_token"]

    req_cross = urllib.request.Request(
        f"{BASE}/dashboard/overview?farm_id=farm-beta",
        headers={"Authorization": f"Bearer {op_token}"}
    )
    try:
        urllib.request.urlopen(req_cross)
        assert False, "Unauthorized cross-farm access should have been rejected!"
    except urllib.error.HTTPError as e:
        assert e.code == 403, f"Expected 403, got {e.code}"
        print("[OK] Cross-farm RBAC security strictly rejected unauthorized operator with 403 Forbidden")

    print("\nALL VERIFICATION CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_api()
