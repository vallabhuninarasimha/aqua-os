"""Health and diagnostic endpoints for Aqua OS API."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from apps.api.src.config import settings
from apps.api.src.dependencies import get_pond_repository, get_telemetry_repository
from apps.api.src.domain.interfaces import IPondRepository, ITelemetryRepository

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReadinessResponse(BaseModel):
    status: str
    active_ponds: int
    total_ponds: int
    ingested_packets_count: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe returning application operational status."""
    return HealthResponse(
        status="healthy",
        app_name=settings.app_name,
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check(
    pond_repo: IPondRepository = Depends(get_pond_repository),
    telemetry_repo: ITelemetryRepository = Depends(get_telemetry_repository),
) -> ReadinessResponse:
    """Readiness probe reporting registered pond count and ingestion health."""
    return ReadinessResponse(
        status="ready",
        active_ponds=pond_repo.count(farm_id=settings.default_farm_id, active_only=True),
        total_ponds=pond_repo.count(farm_id=settings.default_farm_id, active_only=False),
        ingested_packets_count=telemetry_repo.total_ingested_count(),
    )
