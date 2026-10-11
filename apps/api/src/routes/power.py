"""Power monitoring endpoints for farm transformers."""

from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.domain.hardware_interfaces import TransformerPowerStatus
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.power_service import PowerMonitoringService

router = APIRouter(prefix="/farm/power", tags=["Power Infrastructure"])


@router.get("", response_model=List[TransformerPowerStatus])
async def get_farm_power(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> List[TransformerPowerStatus]:
    """Retrieve load, continuous 80% rating headroom, and running equipment for both 23 kW transformers."""
    verify_farm_access(user, farm_id)
    service = PowerMonitoringService(session)
    return service.get_farm_power_summary(farm_id)

