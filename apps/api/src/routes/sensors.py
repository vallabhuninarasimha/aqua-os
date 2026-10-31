"""Sensor management API routes for hardware registration, calibration, and health diagnostics."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.infrastructure.repositories.sql_sensor_repository import SQLSensorRepository
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.sensor_management_service import SensorManagementService

router = APIRouter(prefix="/sensors", tags=["Sensors & Instrumentation"])


class SensorRegistrationRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id, description="Farm identifier")
    pond_id: str = Field(..., description="Pond where sensor is installed")
    sensor_id: str = Field(..., min_length=3, max_length=64, description="Unique hardware EUI or identifier")
    sensor_type: str = Field(..., description="Sensor type: OPTICAL_DO, PH, SALINITY, WATER_LEVEL, ORP, TURBIDITY")
    capabilities: List[str] = Field(..., description="Supported metrics, e.g. ['dissolved_oxygen', 'temperature']")
    protocol: str = Field(default="modbus_rtu", description="Communication protocol: modbus_rtu, modbus_tcp, analog_4_20ma, simulated")
    device_address: int = Field(default=1, ge=1, le=247, description="Modbus slave device address")
    manufacturer: str = Field(default="AquaSensors Ltd", max_length=64)
    model: str = Field(default="AQ-PROBE-485", max_length=64)
    serial_number: Optional[str] = Field(default=None, max_length=64)
    register_map: Dict[str, int] = Field(default_factory=dict, description="Register map mapping metric to register index")
    has_integrated_temp: bool = Field(default=False, description="Whether sensor probe includes PT100/PT1000 temperature element")


class SensorCalibrationRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id)
    pond_id: str = Field(..., description="Pond identifier")
    calibration_type: str = Field(default="TWO_POINT", description="TWO_POINT, ZERO, SPAN, SLOPE_OFFSET")
    pre_calibration_value: float = Field(..., description="Sensor reading before calibration")
    reference_value: float = Field(..., description="Certified standard solution reference value")
    post_calibration_value: float = Field(..., description="Sensor reading after calibration")
    technician_id: str = Field(..., min_length=2, max_length=64, description="Technician operator ID")
    valid_days: int = Field(default=30, ge=1, le=365, description="Days until next calibration due")
    offset: Optional[float] = Field(default=None, description="Explicit calibration offset")
    slope: Optional[float] = Field(default=None, description="Explicit calibration slope")
    notes: Optional[str] = Field(default=None, max_length=500)


class SensorMaintenanceRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id)
    maintenance_type: str = Field(..., description="PROBE_CLEANING, MEMBRANE_REPLACEMENT, ELECTROLYTE_REFILL, OPTICAL_CAP_REPLACEMENT, INSPECTION")
    performed_by: str = Field(..., min_length=2, max_length=64)
    details: Optional[str] = Field(default=None, max_length=500)


@router.get("")
async def list_sensors(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Filter by pond identifier"),
    sensor_type: Optional[str] = Query(default=None, description="Filter by sensor type"),
    health_status: Optional[str] = Query(default=None, description="Filter by health status"),
    is_active: Optional[bool] = Query(default=None, description="Filter active/inactive"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List all registered sensors with telemetry, calibration expiration, and health metadata."""
    verify_farm_access(user, farm_id)
    repo = SQLSensorRepository(session)
    sensors = repo.list_all(
        farm_id=farm_id,
        pond_id=pond_id,
        sensor_type=sensor_type,
        health_status=health_status,
        is_active=is_active,
    )
    return [s.model_dump(mode="json") for s in sensors]


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_sensor(
    payload: SensorRegistrationRequest,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Register a new sensor probe or instrument into the farm inventory."""
    verify_farm_access(user, payload.farm_id)
    service = SensorManagementService(session)
    sensor = service.register_sensor(
        farm_id=payload.farm_id,
        pond_id=payload.pond_id,
        sensor_id=payload.sensor_id,
        sensor_type=payload.sensor_type,
        capabilities=payload.capabilities,
        protocol=payload.protocol,
        device_address=payload.device_address,
        manufacturer=payload.manufacturer,
        model=payload.model,
        serial_number=payload.serial_number,
        register_map=payload.register_map,
        has_integrated_temp=payload.has_integrated_temp,
    )
    return sensor.model_dump(mode="json")


@router.get("/watchdog/status")
async def get_watchdog_status(
    farm_id: str = Query(default=settings.default_farm_id),
    stale_timeout_seconds: int = Query(default=180, ge=10, le=86400),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Run sensor watchdog diagnostics: detects stale probes, expired calibrations, and faults."""
    verify_farm_access(user, farm_id)
    service = SensorManagementService(session)
    return service.run_watchdog(farm_id=farm_id, stale_timeout_seconds=stale_timeout_seconds)


@router.get("/{sensor_id}")
async def get_sensor_detail(
    sensor_id: str,
    farm_id: str = Query(default=settings.default_farm_id),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve full hardware metadata, calibration status, and diagnostic health for a sensor."""
    verify_farm_access(user, farm_id)
    repo = SQLSensorRepository(session)
    sensor = repo.get(sensor_id)
    if not sensor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sensor '{sensor_id}' not found.",
        )
    return sensor.model_dump(mode="json")


@router.post("/{sensor_id}/calibration")
async def calibrate_sensor(
    sensor_id: str,
    payload: SensorCalibrationRequest,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Record an industrial sensor calibration run with pre/post verification and validity period."""
    verify_farm_access(user, payload.farm_id)
    service = SensorManagementService(session)
    try:
        return service.calibrate_sensor(
            farm_id=payload.farm_id,
            pond_id=payload.pond_id,
            sensor_id=sensor_id,
            calibration_type=payload.calibration_type,
            pre_val=payload.pre_calibration_value,
            ref_val=payload.reference_value,
            post_val=payload.post_calibration_value,
            technician_id=payload.technician_id,
            valid_days=payload.valid_days,
            slope=payload.slope,
            offset=payload.offset,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{sensor_id}/calibration/history")
async def get_sensor_calibration_history(
    sensor_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    farm_id: str = Query(default=settings.default_farm_id),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """Fetch historical calibration ledger records for a sensor probe."""
    verify_farm_access(user, farm_id)
    repo = SQLSensorRepository(session)
    return repo.get_calibration_history(sensor_id=sensor_id, limit=limit)


@router.post("/{sensor_id}/maintenance")
async def record_sensor_maintenance(
    sensor_id: str,
    payload: SensorMaintenanceRequest,
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Record probe maintenance: cleaning, membrane replacement, electrolyte refill, or inspection."""
    verify_farm_access(user, payload.farm_id)
    service = SensorManagementService(session)
    try:
        return service.record_maintenance(
            farm_id=payload.farm_id,
            sensor_id=sensor_id,
            maintenance_type=payload.maintenance_type,
            performed_by=payload.performed_by,
            details=payload.details,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{sensor_id}/maintenance/history")
async def get_sensor_maintenance_history(
    sensor_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    farm_id: str = Query(default=settings.default_farm_id),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """Fetch historical maintenance logs for a sensor probe."""
    verify_farm_access(user, farm_id)
    repo = SQLSensorRepository(session)
    return repo.get_maintenance_logs(sensor_id=sensor_id, limit=limit)

