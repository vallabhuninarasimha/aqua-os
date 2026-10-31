"""Read-only aerator status endpoint for the farm visual monitor."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.aerator_status_sync import AeratorStatusSyncService

router = APIRouter(prefix="/equipment/aerators", tags=["Aerator Status"])
status_sync = AeratorStatusSyncService()


@router.get("/status")
async def get_aerator_status(
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> dict:
    """Return the latest farm-scoped aerator feedback with freshness metadata.

    This endpoint is read-only. It does not switch motors or synthesize live
    hardware telemetry when no controller feedback is available.
    """
    verify_farm_access(user, farm_id)
    return status_sync.get_snapshot(session=session, farm_id=farm_id)
