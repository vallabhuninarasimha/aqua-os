"""Telemetry ingestion and query endpoints."""

from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from apps.api.src.config import settings
from apps.api.src.dependencies import (
    get_pond_repository,
    get_safety_evaluator,
    get_telemetry_repository,
)
from apps.api.src.domain.interfaces import (
    IPondRepository,
    ISafetyEvaluator,
    ITelemetryRepository,
)
from apps.api.src.security.dependencies import (
    require_permission,
    verify_farm_access,
)
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.telemetry_broadcaster import broadcaster
from packages.telemetry_schema.models import (
    PondTelemetryPacket,
    SafetyEvaluationResult,
)

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


class PondStatusResponse(BaseModel):
    pond_id: str
    latest_telemetry: Optional[PondTelemetryPacket] = None
    latest_safety_evaluation: Optional[SafetyEvaluationResult] = None


@router.post("", response_model=SafetyEvaluationResult, status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(
    packet: PondTelemetryPacket,
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    pond_repo: IPondRepository = Depends(get_pond_repository),
    telemetry_repo: ITelemetryRepository = Depends(get_telemetry_repository),
    safety_evaluator: ISafetyEvaluator = Depends(get_safety_evaluator),
) -> SafetyEvaluationResult:
    """Ingest a validated sensor telemetry packet from Edge or simulator.

    Requires TELEMETRY_WRITE permission and validates farm ownership.
    Evaluates water quality parameters against the target pond's biological thresholds,
    persists historical and latest records, and returns safety recommendations.
    """
    verify_farm_access(user, packet.farm_id)

    pond_config = pond_repo.get(farm_id=packet.farm_id, pond_id=packet.pond_id)
    evaluation = safety_evaluator.evaluate(packet=packet, pond_config=pond_config)
    telemetry_repo.save(packet=packet, evaluation=evaluation)

    # Real-time event broadcasting
    await broadcaster.broadcast(
        "pond_update",
        {
            "farm_id": packet.farm_id,
            "pond_id": packet.pond_id,
            "packet": packet.model_dump(mode="json"),
            "evaluation": evaluation.model_dump(mode="json"),
        },
    )
    return evaluation


@router.get("/latest", response_model=Dict[str, PondTelemetryPacket])
async def get_all_latest_telemetry(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    telemetry_repo: ITelemetryRepository = Depends(get_telemetry_repository),
) -> Dict[str, PondTelemetryPacket]:
    """Retrieve the latest telemetry readings across all reporting ponds."""
    verify_farm_access(user, farm_id)
    return telemetry_repo.get_all_latest(farm_id=farm_id)


@router.get("/latest/{pond_id}", response_model=PondStatusResponse)
async def get_pond_latest_status(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    telemetry_repo: ITelemetryRepository = Depends(get_telemetry_repository),
) -> PondStatusResponse:
    """Retrieve latest telemetry and safety evaluation for a specific pond."""
    verify_farm_access(user, farm_id)
    result = telemetry_repo.get_latest(farm_id=farm_id, pond_id=pond_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No telemetry data has been received for pond '{pond_id}' on farm '{farm_id}'.",
        )

    telemetry, evaluation = result
    return PondStatusResponse(
        pond_id=pond_id,
        latest_telemetry=telemetry,
        latest_safety_evaluation=evaluation,
    )


@router.get("/history/{pond_id}", response_model=List[PondTelemetryPacket])
async def get_pond_history(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    start_time: Optional[datetime] = Query(
        default=None,
        description="Start timestamp filter (UTC)",
    ),
    end_time: Optional[datetime] = Query(
        default=None,
        description="End timestamp filter (UTC)",
    ),
    limit: int = Query(default=100, ge=1, le=1000, description="Max records to return"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    telemetry_repo: ITelemetryRepository = Depends(get_telemetry_repository),
) -> List[PondTelemetryPacket]:
    """Retrieve historical telemetry packets for a pond within a time window."""
    verify_farm_access(user, farm_id)
    return telemetry_repo.get_history(
        farm_id=farm_id,
        pond_id=pond_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
