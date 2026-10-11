"""Shrimp Growth & Production Intelligence REST routes."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.growth_production_service import GrowthProductionService

router = APIRouter(prefix="/production", tags=["Production Intelligence"])


# ============================================================================
# Request / Response Schemas
# ============================================================================

class BatchCreateRequest(BaseModel):
    species: str = "Litopenaeus vannamei"
    initial_count: int = 150_000
    initial_pl_weight_g: float = 0.05
    seed_supplier: Optional[str] = "Aquaculture SPF Hatchery"
    seed_quality_notes: Optional[str] = "SPF certified postlarvae, 100% active swimming"
    stocking_date: Optional[datetime] = None
    target_abw_g: float = 25.0
    target_harvest_date: Optional[datetime] = None
    projected_sale_price_per_kg: float = 5.50
    estimated_survival_pct: float = 85.0
    status: str = "ACTIVE"


class BatchCloseRequest(BaseModel):
    status: str = "HARVESTED"  # HARVESTED or CLOSED
    harvested_biomass_kg: Optional[float] = None
    harvest_notes: Optional[str] = None


class HarvestPlanUpdateRequest(BaseModel):
    target_abw_g: float = 25.0
    target_harvest_date: Optional[datetime] = None
    projected_sale_price_per_kg: float = 5.50


class GrowthSamplingCreateRequest(BaseModel):
    abw_g: float = Field(..., gt=0.0, description="Average body weight in grams (strictly > 0)")
    sample_count: int = Field(default=50, gt=0, description="Number of individual shrimp sampled")
    measurement_type: str = Field(default="MEASURED", description="MEASURED, ESTIMATED, or MANUAL_ENTRY")
    sampling_method: str = Field(default="Cast net", description="Sampling method used")
    observations: Optional[str] = Field(default=None, description="Gut fullness, hepatopancreas, shell condition")
    estimated_survival_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Updated survival rate if observed")
    sample_date: Optional[datetime] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/farm/summary", response_model=Dict[str, Any])
async def get_farm_production_summary(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve farm-level production rollup: total estimated biomass, cumulative feed, average ABW, DOC, and overall FCR."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.get_farm_production_summary(farm_id)


@router.get("/ponds/{pond_id}/intelligence", response_model=Dict[str, Any])
async def get_pond_production_intelligence(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve pond-specific growth intelligence: DOC, latest ABW, ADG, FCR analysis, and harvest projections."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.get_pond_production_intelligence(farm_id, pond_id)


@router.get("/ponds/{pond_id}/batches", response_model=List[Dict[str, Any]])
async def list_pond_batches(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List production batches (active, harvested, closed) for a pond without overwriting historical data."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.list_batches(farm_id=farm_id, pond_id=pond_id, status=status_filter)


@router.post("/ponds/{pond_id}/batches", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_pond_batch(
    pond_id: str,
    req: BatchCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Register a new production batch for a pond."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    batch_data = req.model_dump()
    batch_data["farm_id"] = farm_id
    batch_data["pond_id"] = pond_id
    return service.create_or_update_batch(batch_data)


@router.post("/batches/{batch_id}/close", response_model=Dict[str, Any])
async def close_batch(
    batch_id: str,
    req: BatchCloseRequest,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Mark a production batch as HARVESTED or CLOSED preserving historical records."""
    service = GrowthProductionService(session)
    res = service.close_or_harvest_batch(
        batch_id=batch_id,
        status=req.status,
        harvested_biomass_kg=req.harvested_biomass_kg,
        harvest_notes=req.harvest_notes,
    )
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found.",
        )
    return res


@router.post("/batches/{batch_id}/harvest-plan", response_model=Dict[str, Any])
async def update_harvest_plan(
    batch_id: str,
    req: HarvestPlanUpdateRequest,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Configure harvest target ABW, estimated harvest date, and projected sale price."""
    service = GrowthProductionService(session)
    batch_dict = service._records_repo.get_batch(batch_id)
    if not batch_dict:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found.",
        )
    batch_dict["target_abw_g"] = req.target_abw_g
    batch_dict["target_harvest_date"] = req.target_harvest_date
    batch_dict["projected_sale_price_per_kg"] = req.projected_sale_price_per_kg
    return service.create_or_update_batch(batch_dict)


@router.get("/ponds/{pond_id}/samples", response_model=List[Dict[str, Any]])
async def list_growth_samples(
    pond_id: str,
    batch_id: Optional[str] = Query(default=None),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List historical growth sampling records for trend charts."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.list_samplings(batch_id=batch_id, pond_id=pond_id)


@router.post("/ponds/{pond_id}/samples", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_growth_sample(
    pond_id: str,
    req: GrowthSamplingCreateRequest,
    batch_id: Optional[str] = Query(default=None),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Record physical or manual shrimp growth sampling point with automated ADG calculation."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    sample_data = req.model_dump()
    sample_data["farm_id"] = farm_id
    sample_data["pond_id"] = pond_id
    sample_data["batch_id"] = batch_id
    sample_data["recorded_by"] = user.username

    try:
        return service.record_sampling(sample_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

