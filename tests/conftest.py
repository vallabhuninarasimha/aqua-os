"""Pytest test fixtures and configuration for Aqua OS."""

from datetime import datetime, timezone
from typing import Dict, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.database import (
    Base,
    SessionLocal,
    engine,
    init_db,
    seed_default_ponds_if_empty,
    seed_default_users_if_empty,
)
from apps.api.src.main import app
from apps.api.src.security.jwt_provider import LocalJWTIdentityProvider
from apps.api.src.security.models import (
    ROLE_PERMISSIONS,
    Role,
    UserIdentity,
)
from packages.telemetry_schema.models import (
    MetricReading,
    MetricType,
    PondTelemetryPacket,
    QualityStatus,
)


@pytest.fixture(autouse=True)
def reset_database():
    """Reset all database tables and seed fresh defaults before each test."""
    Base.metadata.drop_all(bind=engine)
    init_db(engine)
    with SessionLocal() as session:
        seed_default_ponds_if_empty(session, farm_id="farm-alpha")
        seed_default_users_if_empty(session)
    yield


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a direct database session for tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Test client for Aqua OS FastAPI backend."""
    with TestClient(app) as test_client:
        yield test_client


def make_auth_headers(
    user_id: str,
    username: str,
    farm_id: str,
    role: Role,
) -> Dict[str, str]:
    """Helper generating signed Bearer authorization headers for test requests."""
    with SessionLocal() as session:
        idp = LocalJWTIdentityProvider(session)
        user = UserIdentity(
            user_id=user_id,
            username=username,
            farm_id=farm_id,
            role=role,
            permissions=ROLE_PERMISSIONS.get(role, []),
        )
        token_resp = idp.create_access_token(user)
        return {"Authorization": f"Bearer {token_resp.access_token}"}


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return make_auth_headers("usr-admin", "admin", "farm-alpha", Role.SYSTEM_ADMIN)


@pytest.fixture
def operator_headers() -> Dict[str, str]:
    return make_auth_headers("usr-operator", "operator", "farm-alpha", Role.OPERATOR)


@pytest.fixture
def viewer_headers() -> Dict[str, str]:
    return make_auth_headers("usr-viewer", "viewer", "farm-alpha", Role.VIEWER)


@pytest.fixture
def beta_operator_headers() -> Dict[str, str]:
    return make_auth_headers("usr-beta-op", "beta_operator", "farm-beta", Role.OPERATOR)


@pytest.fixture
def sample_telemetry_packet() -> PondTelemetryPacket:
    """Fixture providing a valid 20-pond normal telemetry packet."""
    return PondTelemetryPacket(
        schema_version="1.0",
        farm_id="farm-alpha",
        pond_id="pond-01",
        timestamp=datetime.now(timezone.utc),
        metrics={
            MetricType.DISSOLVED_OXYGEN: MetricReading(
                metric_type=MetricType.DISSOLVED_OXYGEN,
                value=5.8,
                unit="mg/L",
                quality=QualityStatus.GOOD,
            ),
            MetricType.TEMPERATURE: MetricReading(
                metric_type=MetricType.TEMPERATURE,
                value=28.5,
                unit="°C",
                quality=QualityStatus.GOOD,
            ),
            MetricType.PH: MetricReading(
                metric_type=MetricType.PH,
                value=7.9,
                unit="pH",
                quality=QualityStatus.GOOD,
            ),
            MetricType.SALINITY: MetricReading(
                metric_type=MetricType.SALINITY,
                value=25.0,
                unit="ppt",
                quality=QualityStatus.GOOD,
            ),
        },
    )
