"""Automated security test suite for Aqua OS.

Tests authentication, RBAC authorization, token revocation,
rate-limiting lockout, cross-farm isolation, and audit logging.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import AuditLogORM, UserORM
from apps.api.src.security.password import hash_password, verify_password


def test_login_success(client: TestClient):
    """Verify login with correct credentials yields valid token."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "operator_secret_123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "operator"
    assert data["farm_id"] == "farm-alpha"


def test_login_invalid_password_rejected(client: TestClient):
    """Verify incorrect credentials return HTTP 401."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "wrong_password!"},
    )
    assert resp.status_code == 401


def test_login_brute_force_lockout(client: TestClient, db_session: Session):
    """Verify 5 consecutive failed attempts lock the account."""
    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "wrong_password!"},
        )
        assert resp.status_code == 401

    # 6th attempt with CORRECT password must now fail due to lockout
    locked_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "operator_secret_123"},
    )
    assert locked_resp.status_code == 401

    # Verify locked_until is set in DB
    user = db_session.query(UserORM).filter(UserORM.username == "operator").first()
    assert user.locked_until is not None


def test_invalid_token_rejected(client: TestClient):
    """Verify forged or tampered token returns HTTP 401."""
    headers = {"Authorization": "Bearer forged.token.signature"}
    resp = client.get("/api/v1/ponds/summary", headers=headers)
    assert resp.status_code == 401


def test_token_revocation_on_logout(client: TestClient):
    """Verify logged-out tokens are immediately blacklisted."""
    # 1. Login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin_secret_123"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Verify token works
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # 3. Logout
    logout_resp = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200

    # 4. Token must now be rejected
    denied_resp = client.get("/api/v1/auth/me", headers=headers)
    assert denied_resp.status_code == 401


def test_rbac_viewer_cannot_modify_pond(client: TestClient, viewer_headers: dict):
    """Verify VIEWER role cannot modify or create ponds (Least Privilege)."""
    payload = {
        "farm_id": "farm-alpha",
        "pond_id": "pond-99",
        "name": "Unauthorized Pond",
    }
    resp = client.post("/api/v1/ponds", json=payload, headers=viewer_headers)
    assert resp.status_code == 403
    assert "Requires 'ponds:write' permission" in resp.json()["detail"]


def test_cross_farm_access_forbidden(client: TestClient, beta_operator_headers: dict):
    """Verify an operator of farm-beta cannot access farm-alpha data."""
    resp = client.get("/api/v1/ponds/summary?farm_id=farm-alpha", headers=beta_operator_headers)
    assert resp.status_code == 403
    assert "Cross-farm access forbidden" in resp.json()["detail"]


def test_cross_farm_telemetry_spoofing_forbidden(
    client: TestClient,
    beta_operator_headers: dict,
    sample_telemetry_packet,
):
    """Verify an operator from farm-beta cannot submit telemetry for farm-alpha."""
    payload = sample_telemetry_packet.model_dump(mode="json")
    payload["farm_id"] = "farm-alpha"  # Attacking farm-alpha while belonging to farm-beta

    resp = client.post("/api/v1/telemetry", json=payload, headers=beta_operator_headers)
    assert resp.status_code == 403
    assert "Cross-farm access forbidden" in resp.json()["detail"]


def test_system_admin_can_access_all_farms(client: TestClient, admin_headers: dict):
    """Verify SYSTEM_ADMIN possesses global cross-farm supervisory access."""
    resp_alpha = client.get("/api/v1/ponds/summary?farm_id=farm-alpha", headers=admin_headers)
    assert resp_alpha.status_code == 200

    resp_beta = client.get("/api/v1/ponds/summary?farm_id=farm-beta", headers=admin_headers)
    assert resp_beta.status_code == 200


def test_password_hashing_pbkdf2():
    """Verify passwords are never stored in plaintext and use unique salts."""
    pwd = "super_secure_farm_password"
    hash1 = hash_password(pwd)
    hash2 = hash_password(pwd)

    # Hashes must differ because salts are unique
    assert hash1 != hash2
    assert hash1.startswith("pbkdf2_sha256$100000$")
    assert verify_password(pwd, hash1) is True
    assert verify_password("wrong_password", hash1) is False


def test_audit_log_redacts_secrets(client: TestClient, db_session: Session):
    """Verify security audit logs record events while redacting passwords."""
    client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "wrong_password!"},
    )

    # Check audit log in DB
    audit = (
        db_session.query(AuditLogORM)
        .filter(AuditLogORM.action == "LOGIN_FAILED")
        .order_by(AuditLogORM.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.user_id == "operator"
    # Plaintext password must never appear in database audit logs
    if audit.details_json:
        assert "wrong_password!" not in audit.details_json

