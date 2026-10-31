"""Sensor management service for calibration, health monitoring, and maintenance lifecycles."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.hardware_interfaces import (
    SensorMetadata,
    SensorProtocolType,
)
from apps.api.src.infrastructure.models import SensorRegistryORM
from apps.api.src.infrastructure.repositories.sql_sensor_repository import SQLSensorRepository


# Physical range limits for sensor probe health validation
PHYSICAL_METRIC_LIMITS = {
    "dissolved_oxygen": {"min": 0.0, "max": 25.0, "unit": "mg/L"},
    "temperature": {"min": 0.0, "max": 50.0, "unit": "°C"},
    "ph": {"min": 2.0, "max": 12.0, "unit": "pH"},
    "salinity": {"min": 0.0, "max": 60.0, "unit": "ppt"},
    "water_level": {"min": 0.0, "max": 5.0, "unit": "m"},
    "orp": {"min": -1000.0, "max": 1000.0, "unit": "mV"},
    "turbidity": {"min": 0.0, "max": 1000.0, "unit": "NTU"},
}


class SensorManagementService:
    """Industrial sensor probe lifecycle management service."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = SQLSensorRepository(session)

    def register_sensor(
        self,
        farm_id: str,
        pond_id: str,
        sensor_id: str,
        sensor_type: str,
        capabilities: List[str],
        protocol: str = "MODBUS_RTU_RS485",
        device_address: int = 1,
        manufacturer: str = "AquaSensors Ltd",
        model: str = "AQ-PROBE-485",
        serial_number: Optional[str] = None,
        register_map: Optional[Dict[str, int]] = None,
        has_integrated_temp: bool = False,
    ) -> SensorMetadata:
        try:
            proto = SensorProtocolType(protocol.lower())
        except ValueError:
            proto = SensorProtocolType.MODBUS_RTU

        now = datetime.now(timezone.utc)
        meta = SensorMetadata(
            sensor_id=sensor_id,
            farm_id=farm_id,
            pond_id=pond_id,
            sensor_type=sensor_type.upper(),
            protocol=proto,
            device_address=device_address,
            register_map=register_map or {},
            capabilities=capabilities,
            has_integrated_temp=has_integrated_temp,
            status="ONLINE",
            manufacturer=manufacturer,
            model=model,
            serial_number=serial_number or f"SN-{sensor_id.upper()}",
            calibration_date=now,
            calibration_expiry=now + timedelta(days=30),
            health_status="HEALTHY",
            battery_level_pct=100.0,
            last_communication_at=now,
        )
        return self._repo.register(meta)

    def calibrate_sensor(
        self,
        farm_id: str,
        pond_id: str,
        sensor_id: str,
        calibration_type: str,
        pre_val: float,
        ref_val: float,
        post_val: float,
        technician_id: str,
        valid_days: int = 30,
        slope: Optional[float] = None,
        offset: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        sensor = self._repo.get(sensor_id)
        if not sensor:
            raise ValueError(f"Sensor '{sensor_id}' not found.")

        # If slope/offset not directly provided, compute standard linear calibration
        computed_offset = offset if offset is not None else round(ref_val - pre_val, 4)
        computed_slope = slope if slope is not None else 1.0

        valid_until = datetime.now(timezone.utc) + timedelta(days=valid_days)

        history = self._repo.record_calibration(
            farm_id=farm_id,
            pond_id=pond_id,
            sensor_id=sensor_id,
            calibration_type=calibration_type,
            pre_val=pre_val,
            ref_val=ref_val,
            post_val=post_val,
            offset=computed_offset,
            slope=computed_slope,
            technician_id=technician_id,
            valid_until=valid_until,
            notes=notes,
        )

        return {
            "success": True,
            "sensor_id": sensor_id,
            "calibration_id": history.id,
            "calibration_type": calibration_type,
            "offset": computed_offset,
            "slope": computed_slope,
            "valid_until": valid_until.isoformat(),
            "technician_id": technician_id,
        }

    def record_maintenance(
        self,
        farm_id: str,
        sensor_id: str,
        maintenance_type: str,
        performed_by: str,
        details: Optional[str] = None,
    ) -> Dict[str, Any]:
        sensor = self._repo.get(sensor_id)
        if not sensor:
            raise ValueError(f"Sensor '{sensor_id}' not found.")

        log = self._repo.record_maintenance(
            farm_id=farm_id,
            sensor_id=sensor_id,
            maintenance_type=maintenance_type,
            performed_by=performed_by,
            details=details,
        )

        # Update sensor health if cleaned or serviced
        orm = self._session.query(SensorRegistryORM).filter_by(sensor_id=sensor_id).first()
        if orm:
            orm.health_status = "HEALTHY"
            orm.status = "ONLINE"
            self._session.commit()

        return {
            "success": True,
            "sensor_id": sensor_id,
            "maintenance_id": log.id,
            "maintenance_type": maintenance_type,
            "performed_by": performed_by,
            "created_at": log.created_at.isoformat(),
        }

    def validate_reading_bounds(self, metric_type: str, value: float) -> tuple[bool, Optional[str]]:
        """Validate if raw ADC / engineering value is within physical transducer limits."""
        limits = PHYSICAL_METRIC_LIMITS.get(metric_type.lower())
        if not limits:
            return True, None
        if value < limits["min"] or value > limits["max"]:
            return (
                False,
                f"Value {value} {limits['unit']} out of physical range [{limits['min']}, {limits['max']}]. Possible transducer fault.",
            )
        return True, None

    def run_watchdog(self, farm_id: str, stale_timeout_seconds: int = 180) -> Dict[str, Any]:
        """Scan all sensors and detect stale communication, calibration expiry, and faults."""
        sensors = self._repo.list_all(farm_id=farm_id)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=stale_timeout_seconds)

        stale_sensors = []
        expired_calibrations = []
        faulted_sensors = []
        healthy_count = 0

        for s in sensors:
            is_stale = False
            last_comm = s.last_communication_at
            if last_comm is None:
                is_stale = True
            else:
                comm_tz = last_comm if last_comm.tzinfo else last_comm.replace(tzinfo=timezone.utc)
                if comm_tz < cutoff:
                    is_stale = True

            is_expired = False
            if s.calibration_expiry:
                cal_tz = s.calibration_expiry if s.calibration_expiry.tzinfo else s.calibration_expiry.replace(tzinfo=timezone.utc)
                if cal_tz < now:
                    is_expired = True

            if is_stale:
                stale_sensors.append(s.sensor_id)
            if is_expired:
                expired_calibrations.append(s.sensor_id)
            if s.health_status in ("FAULTED", "DEGRADED"):
                faulted_sensors.append(s.sensor_id)
            if not is_stale and not is_expired and s.health_status == "HEALTHY":
                healthy_count += 1

        return {
            "farm_id": farm_id,
            "total_sensors": len(sensors),
            "healthy_count": healthy_count,
            "stale_sensors": stale_sensors,
            "expired_calibrations": expired_calibrations,
            "faulted_sensors": faulted_sensors,
            "evaluated_at": now.isoformat(),
        }

