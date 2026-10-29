"""Feed Planning & Ration Intelligence API Routes for Aqua OS."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.feed_planning_service import FeedPlanningService

router = APIRouter(prefix="/feed-plans", tags=["Feed Planning & Ration Intelligence"])


# ============================================================================
# Request / Response Schemas
# ============================================================================

class FeedPlanCreateRequest(BaseModel):
    pond_id: str = Field(..., description="Target pond identifier")
    plan_date: datetime = Field(..., description="Target plan date")
    planned_daily_kg: float = Field(..., gt=0.0, description="Total planned daily feed in kg (strictly > 0)")
    feeding_sessions_count: int = Field(default=4, ge=1, le=12, description="Number of feeding sessions in day")
    session_times: Optional[List[str]] = Field(default=None, description="Optional slot time labels (e.g. ['06:00', '11:00'])")
    planned_kg_per_session: Optional[float] = Field(default=None, gt=0.0, description="Optional custom kg per session")
    product_id: Optional[str] = Field(default=None, description="Optional feed inventory product identifier")
    feed_type: str = Field(default="Grower Pellet 38%", description="Pellet specification or brand name")
    recommendation_basis: str = Field(default="MANUAL", description="Calculation origin: ADVISORY, MANUAL, CUSTOM")
    ration_inputs: Optional[Dict[str, Any]] = Field(default=None, description="Optional snapshot of inputs used")
    notes: Optional[str] = Field(default=None, description="Optional plan notes")
    auto_approve: bool = Field(default=False, description="Automatically mark as APPROVED upon creation")


class FeedPlanUpdateRequest(BaseModel):
    planned_daily_kg: Optional[float] = Field(default=None, gt=0.0, description="Updated daily feed target kg")
    feeding_sessions_count: Optional[int] = Field(default=None, ge=1, le=12, description="Number of sessions")
    session_times: Optional[List[str]] = Field(default=None, description="Session times")
    product_id: Optional[str] = Field(default=None, description="Product identifier")
    notes: Optional[str] = Field(default=None, description="Notes")


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/overview", response_model=Dict[str, Any])
async def get_daily_farm_plan_overview(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    target_date: Optional[datetime] = Query(default=None, description="Target date for overview (defaults to today)"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve farm-wide daily feed planning overview with planned vs actual progress."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    return service.get_daily_farm_plan_overview(farm_id=farm_id, target_date=target_date)


@router.get("/recommendation/{pond_id}", response_model=Dict[str, Any])
async def get_ration_recommendation(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    sessions_count: int = Query(default=4, ge=1, le=12, description="Requested number of feeding sessions"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Compute advisory daily feed ration based on latest biomass, water quality telemetry, and feeding trays."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    try:
        return service.get_ration_recommendation(
            farm_id=farm_id,
            pond_id=pond_id,
            custom_sessions_count=sessions_count,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=List[Dict[str, Any]])
async def list_feed_plans(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Optional pond filter"),
    batch_id: Optional[str] = Query(default=None, description="Optional batch filter"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Status filter"),
    date_from: Optional[datetime] = Query(default=None, description="Start date filter"),
    date_to: Optional[datetime] = Query(default=None, description="End date filter"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List feed plans matching specified filters."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    return service.list_feed_plans(
        farm_id=farm_id,
        pond_id=pond_id,
        batch_id=batch_id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def create_feed_plan(
    req: FeedPlanCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Create a new daily feed plan for a pond."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    try:
        return service.create_feed_plan(
            farm_id=farm_id,
            pond_id=req.pond_id,
            plan_date=req.plan_date,
            planned_daily_kg=req.planned_daily_kg,
            feeding_sessions_count=req.feeding_sessions_count,
            session_times=req.session_times,
            planned_kg_per_session=req.planned_kg_per_session,
            product_id=req.product_id,
            feed_type=req.feed_type,
            recommendation_basis=req.recommendation_basis,
            ration_inputs=req.ration_inputs,
            notes=req.notes,
            created_by=user.username,
            auto_approve=req.auto_approve,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{plan_id}", response_model=Dict[str, Any])
async def get_feed_plan(
    plan_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve detailed feed plan by ID."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    plan = service.get_feed_plan(farm_id, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed plan '{plan_id}' not found.")
    return plan


@router.patch("/{plan_id}", response_model=Dict[str, Any])
async def update_feed_plan(
    plan_id: str,
    req: FeedPlanUpdateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Update planned daily kg, sessions, or notes for a plan."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    try:
        return service.update_feed_plan(
            farm_id=farm_id,
            plan_id=plan_id,
            planned_daily_kg=req.planned_daily_kg,
            feeding_sessions_count=req.feeding_sessions_count,
            session_times=req.session_times,
            product_id=req.product_id,
            notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{plan_id}/approve", response_model=Dict[str, Any])
async def approve_feed_plan(
    plan_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Approve a draft feed plan for execution."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    try:
        return service.approve_feed_plan(
            farm_id=farm_id,
            plan_id=plan_id,
            operator=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{plan_id}/cancel", response_model=Dict[str, Any])
async def cancel_feed_plan(
    plan_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Cancel a feed plan."""
    verify_farm_access(user, farm_id)
    service = FeedPlanningService(session)
    try:
        return service.cancel_feed_plan(
            farm_id=farm_id,
            plan_id=plan_id,
            operator=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

