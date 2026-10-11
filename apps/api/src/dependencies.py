"""Dependency injection providers for Aqua OS FastAPI backend.

Adheres to Clean Architecture and Dependency Inversion (SOLID):
Route handlers depend strictly on abstract protocols (IPondRepository,
ITelemetryRepository, ISafetyEvaluator) injected at request time.
"""

from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from apps.api.src.domain.interfaces import (
    IPondRepository,
    ISafetyEvaluator,
    ITelemetryRepository,
)
from apps.api.src.domain.water_interfaces import IWaterRepository
from apps.api.src.domain.safety import ThresholdSafetyEvaluator
from apps.api.src.infrastructure.database import SessionLocal
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import (
    SQLTelemetryRepository,
)
from apps.api.src.infrastructure.repositories.sql_water_repository import SQLWaterRepository


def get_db_session() -> Generator[Session, None, None]:
    """Provide a scoped database session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_pond_repository(
    session: Session = Depends(get_db_session),
) -> IPondRepository:
    """Inject pond configuration repository."""
    return SQLPondRepository(session)


def get_telemetry_repository(
    session: Session = Depends(get_db_session),
) -> ITelemetryRepository:
    """Inject telemetry persistence repository."""
    return SQLTelemetryRepository(session)


def get_water_repository(
    session: Session = Depends(get_db_session),
) -> IWaterRepository:
    """Inject water management repository."""
    return SQLWaterRepository(session)


def get_safety_evaluator() -> ISafetyEvaluator:
    """Inject deterministic biological safety rules engine."""
    return ThresholdSafetyEvaluator()
