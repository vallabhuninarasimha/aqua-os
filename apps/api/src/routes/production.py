"""Shrimp Growth & Production Intelligence REST routes."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.growth_production_service import GrowthProductionService
from apps.api.src.domain.shrimp_grading import analyze_shrimp_sample
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository

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


class HarvestRecordCreateRequest(BaseModel):
    pond_id: str = Field(..., description="Target pond identifier")
    batch_id: Optional[str] = Field(default=None, description="Batch identifier; defaults to active batch if omitted")
    harvest_type: str = Field(default="FINAL", description="PARTIAL or FINAL harvest")
    harvest_date: Optional[datetime] = None
    harvested_weight_kg: float = Field(..., gt=0.0, description="Gross harvest yield in kg (strictly > 0)")
    count_pieces: Optional[int] = Field(default=None, ge=1, description="Estimated or counted number of shrimp pieces")
    count_per_kg: Optional[float] = Field(default=None, gt=0.0, description="Shrimp count per kg (heads-on)")
    avg_body_weight_g: Optional[float] = Field(default=None, gt=0.0, description="Average body weight in grams at harvest")
    grade: Optional[str] = Field(default=None, description="Commercial grade, size class, or sorting classification")
    selling_price_per_kg: Optional[float] = Field(default=None, ge=0.0, description="Realized or agreed gate price per kg")
    total_revenue: Optional[float] = Field(default=None, ge=0.0, description="Total gross revenue realized")
    documented_losses_kg: float = Field(default=0.0, ge=0.0, description="Documented handling, transfer, or processing loss")
    buyer: Optional[str] = Field(default=None, description="Procurement partner, processor, or buyer name")
    notes: Optional[str] = Field(default=None, description="Operational observations, harvesting method, ice slurry quality")
    idempotency_key: Optional[str] = Field(default=None, description="Client-generated key to prevent duplicate harvest logging")
    allow_biomass_override: bool = Field(default=False, description="Explicit operator override to permit harvest exceeding estimated remaining biomass")


class GrowthSamplingCreateRequest(BaseModel):
    abw_g: float = Field(..., gt=0.0, description="Average body weight in grams (strictly > 0)")
    sample_count: int = Field(default=50, gt=0, description="Number of individual shrimp sampled")
    measurement_type: str = Field(default="MEASURED", description="MEASURED, ESTIMATED, or MANUAL_ENTRY")
    sampling_method: str = Field(default="Cast net", description="Sampling method used")
    observations: Optional[str] = Field(default=None, description="Gut fullness, hepatopancreas, shell condition")
    estimated_survival_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Updated survival rate if observed")
    sample_date: Optional[datetime] = None


class ShrimpGradeBandRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    min_count_per_kg: float = Field(..., gt=0.0)
    max_count_per_kg: float = Field(..., gt=0.0)


class ShrimpGradingAnalysisRequest(BaseModel):
    weights_g: List[float] = Field(..., min_length=1, max_length=500)
    grade_bands: List[ShrimpGradeBandRequest] = Field(..., min_length=1, max_length=20)


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
    batch = service._records_repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found.",
        )
    verify_farm_access(user, batch["farm_id"])
    res = service.close_or_harvest_batch(
        batch_id=batch_id,
        status=req.status,
        harvested_biomass_kg=req.harvested_biomass_kg,
        harvest_notes=req.harvest_notes,
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
    verify_farm_access(user, batch_dict["farm_id"])
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
    """List historical growth sampling records for trend charts with strict tenant isolation."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)

    # If batch_id supplied, verify it belongs to this pond and farm
    if batch_id:
        batch = service._records_repo.get_batch(batch_id)
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch '{batch_id}' not found.",
            )
        if batch["farm_id"] != farm_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Batch '{batch_id}' belongs to farm '{batch['farm_id']}', not '{farm_id}'.",
            )
        if batch["pond_id"] != pond_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch '{batch_id}' belongs to pond '{batch['pond_id']}', not '{pond_id}'.",
            )

    return service.list_samplings(batch_id=batch_id, pond_id=pond_id, farm_id=farm_id)


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


@router.get("/ponds/{pond_id}/biomass", response_model=Dict[str, Any])
async def get_pond_biomass_estimation(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve dedicated biomass calculation, surviving population bounds, and data freshness quality certification."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.get_biomass_estimation(farm_id=farm_id, pond_id=pond_id)


@router.get("/ponds/{pond_id}/harvest-forecast", response_model=Dict[str, Any])
async def get_pond_harvest_forecast(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve advisory harvest forecast with uncertainty bounds, SGR, and partial harvest deductions."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.get_harvest_forecast(farm_id=farm_id, pond_id=pond_id)


@router.post("/harvests", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_harvest(
    req: HarvestRecordCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Record partial or final harvest with yield, grading, revenue, and idempotency protection."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    harvest_data = req.model_dump()
    harvest_data["farm_id"] = farm_id
    harvest_data["recorded_by"] = user.username
    try:
        return service.record_harvest(harvest_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/harvests", response_model=List[Dict[str, Any]])
async def list_harvests(
    pond_id: Optional[str] = Query(default=None, description="Pond identifier"),
    batch_id: Optional[str] = Query(default=None, description="Batch identifier"),
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    limit: int = Query(default=50, ge=1, le=500),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List historical harvest event records (partial and final harvests)."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.list_harvests(farm_id=farm_id, pond_id=pond_id, batch_id=batch_id, limit=limit)


@router.get("/batches/readiness", response_model=List[Dict[str, Any]])
async def list_batches_readiness(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Optional pond identifier filter"),
    status: Optional[str] = Query(default=None, description="Optional lifecycle status filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """Retrieve farm batches with harvest readiness indicators, confidence states, and target evaluations."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.list_batches_readiness(farm_id=farm_id, pond_id=pond_id, status=status)


@router.get("/batches/{batch_id}/lifecycle", response_model=Dict[str, Any])
async def get_batch_lifecycle(
    batch_id: str,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve full batch lifecycle tracking: stocking, sampling, mortalities, feed, and harvests."""
    service = GrowthProductionService(session)
    batch = service._records_repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found.",
        )
    verify_farm_access(user, batch["farm_id"])
    lifecycle = service.get_batch_lifecycle(batch_id)
    return lifecycle


@router.get("/batches/{batch_id}/economics", response_model=Dict[str, Any])
async def get_batch_economics(
    batch_id: str,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve verified batch economics, attributable costs, and profitability completeness status."""
    service = GrowthProductionService(session)
    batch = service._records_repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found.",
        )
    verify_farm_access(user, batch["farm_id"])
    econ = service.get_batch_economics(batch_id=batch_id, farm_id=batch["farm_id"])
    if not econ:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Economics data for batch '{batch_id}' not found.",
        )
    return econ


@router.get("/farm/economics", response_model=Dict[str, Any])
async def get_farm_economics(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Optional pond filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve farm-level economics and attributable profitability rollup."""
    verify_farm_access(user, farm_id)
    service = GrowthProductionService(session)
    return service.get_farm_economics_summary(farm_id=farm_id, pond_id=pond_id)






@router.post("/ponds/{pond_id}/grading/analyze", response_model=Dict[str, Any])
async def analyze_pond_shrimp_grading(
    pond_id: str,
    req: ShrimpGradingAnalysisRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Classify an individually weighed shrimp sample using farm-configured count/kg bands."""
    verify_farm_access(user, farm_id)
    if SQLPondRepository(session).get(farm_id, pond_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pond not found in this farm.")
    try:
        result = analyze_shrimp_sample(
            weights_g=req.weights_g,
            grade_bands=[band.model_dump() for band in req.grade_bands],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    result.update({
        "farm_id": farm_id,
        "pond_id": pond_id,
        "analyzed_by": user.username,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    })
    return result
