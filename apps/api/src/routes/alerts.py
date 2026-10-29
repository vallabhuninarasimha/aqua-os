"""Alert lifecycle and acknowledge/resolve routes."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.infrastructure.repositories.sql_alert_repository import SQLAlertRepository
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity

router = APIRouter(prefix="/alerts", tags=["Alerts"])


class AlertActionRequest(BaseModel):
    notes: Optional[str] = None


@router.get("", response_model=List[Dict[str, Any]])
async def list_alerts(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Optional pond filter"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="ACTIVE, ACKNOWLEDGED, RESOLVED"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List alerts with lifecycle status and timestamps."""
    verify_farm_access(user, farm_id)
    repo = SQLAlertRepository(session)
    return repo.list(farm_id=farm_id, pond_id=pond_id, status=status_filter)


@router.post("/{alert_id}/acknowledge", response_model=Dict[str, Any])
async def acknowledge_alert(
    alert_id: str,
    action: AlertActionRequest = AlertActionRequest(),
    user: UserIdentity = Depends(require_permission(Permission.ADVISORY_ACK)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Acknowledge an active alert scoped to authorized farm."""
    repo = SQLAlertRepository(session)
    # Check alert existence across database to verify farm ownership before mutation
    unscoped_alert = repo.get_alert(alert_id)
    if not unscoped_alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID '{alert_id}' not found.",
        )
    target_farm_id = unscoped_alert["farm_id"]
    verify_farm_access(user, target_farm_id)

    # Perform farm-scoped mutation
    effective_farm_id = None if user.role.value == "system_admin" else user.farm_id
    result = repo.acknowledge(alert_id=alert_id, acknowledged_by=user.username, farm_id=effective_farm_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID '{alert_id}' not found.",
        )
    return result


@router.post("/{alert_id}/resolve", response_model=Dict[str, Any])
async def resolve_alert(
    alert_id: str,
    action: AlertActionRequest = AlertActionRequest(),
    user: UserIdentity = Depends(require_permission(Permission.ADVISORY_ACK)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Resolve an active or acknowledged alert scoped to authorized farm."""
    repo = SQLAlertRepository(session)
    unscoped_alert = repo.get_alert(alert_id)
    if not unscoped_alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID '{alert_id}' not found.",
        )
    target_farm_id = unscoped_alert["farm_id"]
    verify_farm_access(user, target_farm_id)

    effective_farm_id = None if user.role.value == "system_admin" else user.farm_id
    result = repo.resolve(alert_id=alert_id, resolved_by=user.username, farm_id=effective_farm_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID '{alert_id}' not found.",
        )
    return result

