"""Pond Health, Mortality & Treatment Management REST routes."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.health_service import HealthService

router = APIRouter(prefix="/health", tags=["Pond Health & Treatments"])


# ============================================================================
# Schemas
# ============================================================================

class MortalityCreateRequest(BaseModel):
    dead_count: int = Field(..., ge=1, description="Number of dead shrimp collected")
    collection_method: str = Field(default="Central drain siphon", description="Collection or observation method")
    suspected_reason: str = Field(default="Unknown", description="Suspected biological reason")
    doc: Optional[int] = Field(default=None, ge=0, description="Override DOC if known")
    notes: Optional[str] = Field(default=None, description="Observation or situational notes")
    recorded_at: Optional[datetime] = None


class MortalityCorrectionRequest(BaseModel):
    corrected_dead_count: int = Field(..., ge=0, description="Audited dead count")
    correction_notes: str = Field(..., min_length=3, description="Audit reason for modifying recorded dead count")


class HealthObservationCreateRequest(BaseModel):
    sample_count: int = Field(default=20, ge=1, description="Sample size inspected")
    observation_method: str = Field(default="Feeding tray inspection")
    swimming_activity: str = Field(default="NORMAL", description="NORMAL, LETHARGIC, SURFACING, SPIRALING")
    feed_response: str = Field(default="NORMAL", description="NORMAL, VIGOROUS, POOR, NONE")
    shell_body_condition: str = Field(default="NORMAL_CLEAN", description="NORMAL_CLEAN, SOFT_SHELL, FOULING, DEFORMITY")
    gill_condition: str = Field(default="CLEAN_TRANSLUCENT", description="CLEAN_TRANSLUCENT, BLACK, BROWN, FOUL")
    gut_condition: str = Field(default="FULL_CONTINUOUS", description="FULL_CONTINUOUS, BROKEN, EMPTY")
    coloration: str = Field(default="NORMAL_TRANSLUCENT", description="NORMAL_TRANSLUCENT, RED_BODY, OPAQUE_WHITISH")
    visible_lesions: str = Field(default="NONE", description="NONE, MELANIZED_SPOTS, ANTENNAL_DAMAGE, UROPOD_EROSION")
    severity: str = Field(default="NORMAL", description="NORMAL, MILD, MODERATE, SEVERE")
    doc: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None
    photo_reference_url: Optional[str] = None
    recorded_at: Optional[datetime] = None


class TreatmentCreateRequest(BaseModel):
    product_name: str = Field(..., min_length=1, description="Product commercial or trade name")
    dosage_amount: float = Field(..., gt=0.0, description="Dosage quantity entered by operator")
    reason_for_treatment: str = Field(..., min_length=1, description="Targeted issue (e.g. Probiotic water balance, Mineral booster)")
    dosage_unit: str = Field(default="kg/ha", description="Measurement units (e.g. kg/ha, L/pond, ppm)")
    active_ingredient: Optional[str] = Field(default=None, description="Active chemical or biological agent")
    withdrawal_period_days: int = Field(default=0, ge=0, description="Mandatory harvest withdrawal days (0 if none)")
    product_label_info: Optional[str] = Field(default=None, description="Manufacturer instructions and safety guidelines")
    doc: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None
    applied_at: Optional[datetime] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/ponds/{pond_id}/summary", response_model=Dict[str, Any])
async def get_pond_health_summary(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve full health status: population metrics, 24h mortality, withdrawal restrictions, and observation timeline."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    return service.get_pond_health_summary(farm_id, pond_id)


# --- Mortality Endpoints ---

@router.post("/ponds/{pond_id}/mortality", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_mortality(
    pond_id: str,
    req: MortalityCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Log physical dead shrimp collection, recalculate survival metrics, and evaluate mortality alerts."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    return service.record_mortality(
        farm_id=farm_id,
        pond_id=pond_id,
        dead_count=req.dead_count,
        collection_method=req.collection_method,
        suspected_reason=req.suspected_reason,
        doc=req.doc,
        notes=req.notes,
        recorded_by=user.username,
        recorded_at=req.recorded_at,
    )


@router.get("/ponds/{pond_id}/mortality", response_model=List[Dict[str, Any]])
async def list_mortalities(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List historical mortality records for a pond."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    return service.list_mortalities(farm_id=farm_id, pond_id=pond_id, limit=limit)


@router.post("/mortality/{mortality_id}/correct", response_model=Dict[str, Any])
async def correct_mortality(
    mortality_id: str,
    req: MortalityCorrectionRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Audit correction of a previously recorded dead count."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    updated = service.correct_mortality(
        farm_id=farm_id,
        mortality_id=mortality_id,
        corrected_dead_count=req.corrected_dead_count,
        correction_notes=req.correction_notes,
        corrected_by=user.username,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mortality record '{mortality_id}' not found.",
        )
    return updated


# --- Health Observations Endpoints ---

@router.post("/ponds/{pond_id}/observations", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_health_observation(
    pond_id: str,
    req: HealthObservationCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Log observational health signs with concurrent water quality telemetry snapshot."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    return service.record_health_observation(
        farm_id=farm_id,
        pond_id=pond_id,
        sample_count=req.sample_count,
        observation_method=req.observation_method,
        swimming_activity=req.swimming_activity,
        feed_response=req.feed_response,
        shell_body_condition=req.shell_body_condition,
        gill_condition=req.gill_condition,
        gut_condition=req.gut_condition,
        coloration=req.coloration,
        visible_lesions=req.visible_lesions,
        severity=req.severity,
        doc=req.doc,
        notes=req.notes,
        photo_reference_url=req.photo_reference_url,
        recorded_by=user.username,
        recorded_at=req.recorded_at,
    )


@router.get("/ponds/{pond_id}/observations", response_model=List[Dict[str, Any]])
async def list_health_observations(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List clinical observations for a pond."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    return service.list_health_observations(farm_id=farm_id, pond_id=pond_id, limit=limit)


# --- Treatment Endpoints ---

@router.post("/ponds/{pond_id}/treatments", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_treatment(
    pond_id: str,
    req: TreatmentCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Record product application and compute harvest withdrawal restriction window."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    return service.record_treatment(
        farm_id=farm_id,
        pond_id=pond_id,
        product_name=req.product_name,
        dosage_amount=req.dosage_amount,
        reason_for_treatment=req.reason_for_treatment,
        dosage_unit=req.dosage_unit,
        active_ingredient=req.active_ingredient,
        withdrawal_period_days=req.withdrawal_period_days,
        product_label_info=req.product_label_info,
        doc=req.doc,
        notes=req.notes,
        recorded_by=user.username,
        applied_at=req.applied_at,
    )


@router.get("/ponds/{pond_id}/treatments", response_model=List[Dict[str, Any]])
async def list_treatments(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List treatments and applications for a pond."""
    verify_farm_access(user, farm_id)
    service = HealthService(session)
    return service.list_treatments(farm_id=farm_id, pond_id=pond_id, limit=limit)

