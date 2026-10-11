"""Pond management and configuration routes."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session, get_pond_repository
from apps.api.src.domain.interfaces import IPondRepository
from apps.api.src.security.audit import log_security_event
from apps.api.src.security.dependencies import (
    require_permission,
    verify_farm_access,
)
from apps.api.src.security.models import Permission, UserIdentity
from packages.telemetry_schema.config import PondConfig

router = APIRouter(prefix="/ponds", tags=["Ponds"])


class FarmSummaryResponse(BaseModel):
    farm_id: str
    name: str
    location: str
    active_ponds: int
    total_ponds: int
    telemetry_interval_seconds: int


@router.get("/summary", response_model=FarmSummaryResponse)
async def get_farm_summary(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    repo: IPondRepository = Depends(get_pond_repository),
) -> FarmSummaryResponse:
    """Retrieve high-level farm overview and active pond counts."""
    verify_farm_access(user, farm_id)
    return FarmSummaryResponse(
        farm_id=farm_id,
        name="Aqua OS Core Farm",
        location="Coastal Aquaculture Zone",
        active_ponds=repo.count(farm_id=farm_id, active_only=True),
        total_ponds=repo.count(farm_id=farm_id, active_only=False),
        telemetry_interval_seconds=10,
    )


@router.get("", response_model=List[PondConfig])
async def list_ponds(
    farm_id: Optional[str] = Query(default=None, description="Optional farm filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    repo: IPondRepository = Depends(get_pond_repository),
) -> List[PondConfig]:
    """List all configured ponds for authorized farm."""
    target_farm = farm_id or user.farm_id
    verify_farm_access(user, target_farm)
    return repo.list(farm_id=target_farm)


@router.get("/{pond_id}", response_model=PondConfig)
async def get_pond(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    repo: IPondRepository = Depends(get_pond_repository),
) -> PondConfig:
    """Get configuration and biological thresholds for a specific pond."""
    verify_farm_access(user, farm_id)
    pond = repo.get(farm_id=farm_id, pond_id=pond_id)
    if not pond:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pond with ID '{pond_id}' not found for farm '{farm_id}'.",
        )
    return pond


@router.post("", response_model=PondConfig, status_code=status.HTTP_201_CREATED)
async def register_or_update_pond(
    pond: PondConfig,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
    repo: IPondRepository = Depends(get_pond_repository),
) -> PondConfig:
    """Register a new pond or update existing thresholds dynamically.

    Requires PONDS_WRITE permission and logs an immutable security audit trail.
    """
    verify_farm_access(user, pond.farm_id)
    saved_pond = repo.save(pond)

    log_security_event(
        session=session,
        farm_id=pond.farm_id,
        user_id=user.user_id,
        action="POND_CONFIG_UPDATE",
        resource_type="pond",
        resource_id=pond.pond_id,
        details={"pond_id": pond.pond_id, "aerator_count": pond.aerator_count},
    )
    return saved_pond


# ============================================================================
# Pond-Specific Hardware, Aeration, Biomass, and Feeding Endpoints
# ============================================================================

class CalibrationRequest(BaseModel):
    offset: float = 0.0
    slope: float = 1.0


class FeedingLogRequest(BaseModel):
    feed_kg: float = Field(..., gt=0.0, description="Feed quantity in kg (strictly > 0)")
    feed_type: str = Field(default="Grower Pellet 38%", description="Feed product or pellet specification")
    feed_time_label: str = Field(default="06:00 Morning", description="Ration time slot label")
    feeding_event_count: int = Field(default=1, ge=1, description="Number of feeding applications represented")
    tray_observation: str = Field(default="Clean / 100% Consumed", description="Check tray consumption observation")
    notes: Optional[str] = Field(default=None, description="Optional operator notes")
    batch_id: Optional[str] = Field(default=None, description="Optional target batch identifier")
    timestamp: Optional[datetime] = Field(default=None, description="Optional timestamp of feeding application")


class StockingBatchUpdateRequest(BaseModel):
    species: Optional[str] = "Litopenaeus vannamei"
    initial_count: Optional[int] = None
    days_of_culture: Optional[int] = None
    estimated_survival_pct: Optional[float] = None
    avg_body_weight_g: Optional[float] = None


@router.get("/{pond_id}/detail")
async def get_pond_detail(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
):
    """Retrieve comprehensive pond monitoring state: telemetry, sensors, aerators, aeration advisory, biomass, alerts, and feeding logs."""
    from apps.api.src.services.pond_monitoring_service import PondMonitoringService

    verify_farm_access(user, farm_id)
    service = PondMonitoringService(session)
    detail = service.get_pond_detail(farm_id=farm_id, pond_id=pond_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pond '{pond_id}' not found for farm '{farm_id}'.",
        )
    return detail


@router.get("/{pond_id}/sensors")
async def list_pond_sensors(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
):
    """List physical Modbus sensors registered for this pond."""
    from apps.api.src.infrastructure.repositories.sql_sensor_repository import SQLSensorRepository

    verify_farm_access(user, farm_id)
    repo = SQLSensorRepository(session)
    sensors = repo.list_by_pond(farm_id, pond_id)
    if not sensors:
        repo.seed_defaults_for_pond(farm_id, pond_id)
        sensors = repo.list_by_pond(farm_id, pond_id)
    return [s.model_dump(mode="json") for s in sensors]


@router.post("/{pond_id}/sensors/{sensor_id}/calibration")
async def calibrate_sensor(
    pond_id: str,
    sensor_id: str,
    req: CalibrationRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
):
    """Update sensor calibration slope and offset."""
    from apps.api.src.services.pond_monitoring_service import PondMonitoringService

    verify_farm_access(user, farm_id)
    service = PondMonitoringService(session)
    updated = service.calibrate_sensor(
        sensor_id=sensor_id,
        calibration_offset=req.offset,
        calibration_slope=req.slope,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sensor '{sensor_id}' not found.",
        )
    return updated.model_dump(mode="json")


@router.get("/{pond_id}/aeration")
async def get_pond_aeration(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
):
    """Get pond aerator statuses, runtime history, and current advisory aeration decision."""
    from apps.api.src.services.pond_monitoring_service import PondMonitoringService

    verify_farm_access(user, farm_id)
    service = PondMonitoringService(session)
    detail = service.get_pond_detail(farm_id, pond_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Pond not found")
    return {
        "pond_id": pond_id,
        "aerators": detail["aerators"],
        "aeration_decision": detail["aeration_decision"],
        "aeration_runtime_summary": detail.get("aeration_runtime_summary"),
        "aeration_runtime_history": detail.get("aeration_runtime_history"),
        "aeration_decision_history": detail.get("aeration_decision_history"),
        "transformer_status": detail["transformer_status"],
    }


@router.post("/{pond_id}/aeration/dry-run")
async def trigger_aeration_dry_run(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.ADVISORY_ACK)),
    session: Session = Depends(get_db_session),
):
    """Run advisory dry-run aeration decision evaluation without executing hardware actuator commands."""
    from apps.api.src.services.pond_monitoring_service import PondMonitoringService

    verify_farm_access(user, farm_id)
    service = PondMonitoringService(session)
    decision = service.evaluate_aeration_dry_run(
        farm_id=farm_id, pond_id=pond_id, operator_id=user.username
    )
    return decision.model_dump(mode="json")


class AeratorOverrideRequest(BaseModel):
    aerator_id: str
    desired_state: str  # AUTO, FORCE_ON, FORCE_OFF


@router.put("/{pond_id}/aeration/override")
async def set_aerator_override(
    pond_id: str,
    payload: AeratorOverrideRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.ADVISORY_ACK)),
    session: Session = Depends(get_db_session),
):
    """Set manual desired state override (AUTO, FORCE_ON, FORCE_OFF) in DRY_RUN mode."""
    from apps.api.src.domain.hardware_interfaces import DesiredEquipmentState
    from apps.api.src.infrastructure.repositories.sql_aerator_repository import SQLAeratorRepository

    verify_farm_access(user, farm_id)
    repo = SQLAeratorRepository(session)
    aerator = repo.get(payload.aerator_id)
    if not aerator or aerator.pond_id != pond_id:
        raise HTTPException(status_code=404, detail="Aerator not found in pond")

    try:
        new_state = DesiredEquipmentState(payload.desired_state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid desired state: {payload.desired_state}")

    aerator.desired_state = new_state
    saved = repo.save(aerator)
    log_security_event(
        session=session,
        farm_id=farm_id,
        user_id=user.username,
        action="AERATOR_DESIRED_STATE_OVERRIDE",
        resource_type="aerator",
        resource_id=payload.aerator_id,
        details={"pond_id": pond_id, "new_state": new_state.value},
    )
    return saved.model_dump(mode="json")


@router.get("/{pond_id}/stocking")
async def get_stocking_batch(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
):
    """Retrieve active stocking batch, survival rate, ABW, and estimated biomass."""
    from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository

    verify_farm_access(user, farm_id)
    repo = SQLPondRecordsRepository(session)
    batch = repo.get_active_batch(pond_id)
    if not batch:
        repo.seed_default_stocking_for_pond(farm_id, pond_id)
        batch = repo.get_active_batch(pond_id)
    return batch


@router.post("/{pond_id}/stocking")
async def update_stocking_batch(
    pond_id: str,
    req: StockingBatchUpdateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
):
    """Update stocking metrics, days of culture, or average body weight."""
    from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository

    verify_farm_access(user, farm_id)
    repo = SQLPondRecordsRepository(session)
    batch = repo.get_active_batch(pond_id)
    update_data = {
        "farm_id": farm_id,
        "pond_id": pond_id,
        "batch_id": batch["batch_id"] if batch else None,
        "species": req.species or (batch["species"] if batch else "Litopenaeus vannamei"),
        "initial_count": req.initial_count or (batch["initial_count"] if batch else 150_000),
        "days_of_culture": req.days_of_culture or (batch["days_of_culture"] if batch else 35),
        "estimated_survival_pct": req.estimated_survival_pct or (batch["estimated_survival_pct"] if batch else 82.0),
        "avg_body_weight_g": req.avg_body_weight_g or (batch["avg_body_weight_g"] if batch else 8.5),
        "status": "ACTIVE",
    }
    return repo.save_batch(update_data)


@router.get("/{pond_id}/feeding")
async def list_feeding_logs(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    batch_id: Optional[str] = Query(default=None, description="Optional batch filter"),
    start_date: Optional[datetime] = Query(default=None, description="Filter from timestamp"),
    end_date: Optional[datetime] = Query(default=None, description="Filter up to timestamp"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
):
    """List manual feeding records with optional batch and date-range filters."""
    from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository

    verify_farm_access(user, farm_id)
    repo = SQLPondRecordsRepository(session)
    return repo.list_feeding_logs(
        farm_id=farm_id,
        pond_id=pond_id,
        batch_id=batch_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@router.post("/{pond_id}/feeding", status_code=status.HTTP_201_CREATED)
async def log_manual_feeding(
    pond_id: str,
    req: FeedingLogRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    session: Session = Depends(get_db_session),
):
    """Submit a manual feed application with feed amount, check tray observation, and batch association."""
    from apps.api.src.services.pond_monitoring_service import PondMonitoringService

    verify_farm_access(user, farm_id)
    service = PondMonitoringService(session)
    try:
        return service.log_manual_feeding(
            farm_id=farm_id,
            pond_id=pond_id,
            feed_kg=req.feed_kg,
            feed_type=req.feed_type,
            feed_time_label=req.feed_time_label,
            tray_observation=req.tray_observation,
            notes=req.notes,
            recorded_by=user.username,
            batch_id=req.batch_id,
            feeding_event_count=req.feeding_event_count,
            timestamp=req.timestamp,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{pond_id}/feeding/summary", response_model=Dict[str, Any])
async def get_pond_feeding_summary(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    batch_id: Optional[str] = Query(default=None, description="Optional batch filter"),
    days: int = Query(default=14, ge=1, le=90, description="Number of historical days for daily summary"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve daily feeding summary, cumulative feed, moving averages, FCR, and operational advisories."""
    from apps.api.src.services.growth_production_service import GrowthProductionService

    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.get_pond_feeding_summary(
        farm_id=farm_id,
        pond_id=pond_id,
        batch_id=batch_id,
        days=days,
    )


@router.get("/{pond_id}/feeding/advisories", response_model=List[Dict[str, Any]])
async def get_pond_feeding_advisories(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    batch_id: Optional[str] = Query(default=None, description="Optional batch filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """Retrieve operational feeding advisories based on validated farm patterns and check trays."""
    from apps.api.src.services.growth_production_service import GrowthProductionService

    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.get_pond_feeding_advisories(
        farm_id=farm_id,
        pond_id=pond_id,
        batch_id=batch_id,
    )

