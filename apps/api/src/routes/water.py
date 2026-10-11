"""Water Management API endpoints for Aqua OS.

Provides RESTful operations for:
- Simulated water-level monitoring and freshness tracking
- Configurable pond water-level targets and safe boundaries
- Normal and full-drain outlet status tracking (full-drain locked by default)
- Farm-level intake-pump representation and dry-run advisory evaluation
- Water-exchange operation logging and audit history
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session, get_water_repository
from apps.api.src.domain.water_interfaces import (
    GateState,
    IWaterRepository,
    PumpAdvisoryDecision,
    PumpOperationalState,
    WaterManagementMode,
)
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.water_service import WaterManagementService

router = APIRouter(prefix="/water", tags=["Water Management"])


# -----------------------------------------------------------------------------
# Request Schemas
# -----------------------------------------------------------------------------
class UpdatePondTargetsRequest(BaseModel):
    target_m: float = Field(..., ge=0.2, le=3.0, description="Target depth in meters")
    min_m: float = Field(..., ge=0.1, le=2.5, description="Minimum safe water level in meters")
    max_m: float = Field(..., ge=0.3, le=3.5, description="Maximum safe freeboard water level in meters")


class UpdateOutletStateRequest(BaseModel):
    normal_outlet_state: Optional[GateState] = None
    full_drain_outlet_state: Optional[GateState] = None
    full_drain_locked: Optional[bool] = None
    drain_lock_reason: Optional[str] = None


class UpdatePumpConfigRequest(BaseModel):
    transformer_id: str = Field(..., description="Electrical transformer feeder (e.g. tx-1 or tx-2)")
    motor_hp: Optional[float] = Field(None, ge=1.0, le=100.0)
    rating_kw: Optional[float] = Field(None, ge=0.5, le=75.0)


class UpdatePumpStateRequest(BaseModel):
    desired_state: str = Field(default="OFF")
    physical_state: PumpOperationalState = Field(default=PumpOperationalState.OFF)
    current_draw_amps: float = Field(default=0.0, ge=0.0)
    power_kw: float = Field(default=0.0, ge=0.0)


class LogWaterExchangeRequest(BaseModel):
    pond_id: str
    mode: WaterManagementMode = Field(default=WaterManagementMode.NORMAL_MAINTENANCE)
    initial_level_m: float = Field(..., ge=0.0, le=3.5)
    final_level_m: Optional[float] = Field(None, ge=0.0, le=3.5)
    notes: Optional[str] = None


class CompleteWaterExchangeRequest(BaseModel):
    final_level_m: float = Field(..., ge=0.0, le=3.5)
    notes: Optional[str] = None


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@router.get("/ponds", response_model=List[Dict[str, Any]])
async def list_pond_water_statuses(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> List[Dict[str, Any]]:
    """List simulated water levels, reading freshness, outlet statuses, and alerts for all ponds."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    return service.list_farm_water_status(farm_id)


@router.get("/ponds/{pond_id}", response_model=Dict[str, Any])
async def get_pond_water_status(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Retrieve water level, freshness, target depths, and dual-outlet status for a specific pond."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    try:
        return service.get_pond_water_status(farm_id, pond_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/ponds/{pond_id}/targets", response_model=Dict[str, Any])
async def update_pond_water_targets(
    pond_id: str,
    payload: UpdatePondTargetsRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Update configurable water level target depth and safe min/max limits for a pond."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    try:
        updated = service.update_pond_level_targets(
            farm_id=farm_id,
            pond_id=pond_id,
            target_m=payload.target_m,
            min_m=payload.min_m,
            max_m=payload.max_m,
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pond '{pond_id}' not found.")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/ponds/{pond_id}/outlets", response_model=Dict[str, Any])
async def update_pond_outlets(
    pond_id: str,
    payload: UpdateOutletStateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Update normal outlet and full-drain outlet gate state and locks.
    
    Full-drain outlet defaults to locked. Automatic drainage is disabled.
    """
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    try:
        updated = service.update_pond_outlet_state(
            farm_id=farm_id,
            pond_id=pond_id,
            normal_outlet_state=payload.normal_outlet_state.value if payload.normal_outlet_state else None,
            full_drain_outlet_state=payload.full_drain_outlet_state.value if payload.full_drain_outlet_state else None,
            full_drain_locked=payload.full_drain_locked,
            drain_lock_reason=payload.drain_lock_reason,
            operator_id=user.username,
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pond '{pond_id}' not found.")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/pump", response_model=Dict[str, Any])
async def get_pump_status(
    pump_id: str = Query(default="pump-river-intake-01", description="Pump ID"),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Retrieve farm intake pump configuration, assigned transformer, and running telemetry."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    pump = service.get_pump_info(farm_id=farm_id, pump_id=pump_id)
    if not pump:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pump '{pump_id}' not found.")
    return pump


@router.put("/pump/config", response_model=Dict[str, Any])
async def update_pump_config(
    payload: UpdatePumpConfigRequest,
    pump_id: str = Query(default="pump-river-intake-01", description="Pump ID"),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Configure pump specs and assigned electrical transformer feeder."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    updated = service.update_pump_config(
        farm_id=farm_id,
        pump_id=pump_id,
        transformer_id=payload.transformer_id,
        motor_hp=payload.motor_hp,
        rating_kw=payload.rating_kw,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pump '{pump_id}' not found.")
    return updated


@router.post("/pump/state", response_model=Dict[str, Any])
async def update_pump_state(
    payload: UpdatePumpStateRequest,
    pump_id: str = Query(default="pump-river-intake-01", description="Pump ID"),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Update running electrical measurements or dry-run desired state for the intake pump."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    updated = service.update_pump_state(
        farm_id=farm_id,
        pump_id=pump_id,
        desired_state=payload.desired_state,
        physical_state=payload.physical_state.value,
        current_draw_amps=payload.current_draw_amps,
        power_kw=payload.power_kw,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pump '{pump_id}' not found.")
    return updated


@router.get("/pump/advisory", response_model=PumpAdvisoryDecision)
async def evaluate_pump_advisory(
    pump_id: str = Query(default="pump-river-intake-01", description="Pump ID"),
    target_pond_id: Optional[str] = Query(default=None, description="Optional target pond ID"),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> PumpAdvisoryDecision:
    """Evaluate intake-pump advisory against transformer headroom and target pond depth.
    
    Execution mode is strictly DRY_RUN. Physical hardware commands remain disabled.
    """
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    return service.evaluate_pump_advisory(
        farm_id=farm_id,
        pump_id=pump_id,
        target_pond_id=target_pond_id,
        operator_id=user.username,
    )


@router.get("/exchanges", response_model=List[Dict[str, Any]])
async def list_water_exchanges(
    pond_id: Optional[str] = Query(default=None, description="Optional pond filter"),
    limit: int = Query(default=50, ge=1, le=200),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> List[Dict[str, Any]]:
    """List historical water exchange, leveling, and drainage operation logs."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    return service.list_water_exchange_logs(farm_id=farm_id, pond_id=pond_id, limit=limit)


@router.post("/exchanges", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def log_water_exchange(
    payload: LogWaterExchangeRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Record initiation of a water exchange or drainage operation."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    try:
        return service.log_water_exchange(
            farm_id=farm_id,
            pond_id=payload.pond_id,
            mode=payload.mode.value,
            initial_level_m=payload.initial_level_m,
            operator_id=user.username,
            final_level_m=payload.final_level_m,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/exchanges/{exchange_id}/complete", response_model=Dict[str, Any])
async def complete_water_exchange(
    exchange_id: str,
    payload: CompleteWaterExchangeRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    session: Session = Depends(get_db_session),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Mark an ongoing water exchange operation as completed with final water depth."""
    verify_farm_access(user, farm_id)
    service = WaterManagementService(session=session, water_repo=water_repo)
    completed = service.complete_water_exchange(
        farm_id=farm_id,
        exchange_id=exchange_id,
        final_level_m=payload.final_level_m,
        notes=payload.notes,
    )
    if not completed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Water exchange log '{exchange_id}' not found for farm '{farm_id}'.",
        )
    return completed

