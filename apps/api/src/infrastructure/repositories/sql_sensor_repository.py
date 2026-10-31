"""SQL repository for physical and logical sensor metadata."""

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from apps.api.src.domain.hardware_interfaces import (
    ISensorRegistry,
    SensorMetadata,
    SensorProtocolType,
)
from apps.api.src.infrastructure.models import (
    SensorCalibrationHistoryORM,
    SensorMaintenanceLogORM,
    SensorRegistryORM,
)


class SQLSensorRepository(ISensorRegistry):
    """SQL-backed storage for sensor probe hardware registry, calibrations, and maintenance."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def register(self, sensor: SensorMetadata) -> SensorMetadata:
        existing = (
            self._session.query(SensorRegistryORM)
            .filter(SensorRegistryORM.sensor_id == sensor.sensor_id)
            .first()
        )
        if existing:
            existing.sensor_type = sensor.sensor_type
            existing.protocol = sensor.protocol.value
            existing.device_address = sensor.device_address
            existing.register_map_json = json.dumps(sensor.register_map)
            existing.capabilities_json = json.dumps(sensor.capabilities)
            existing.has_integrated_temp = sensor.has_integrated_temp
            existing.calibration_date = sensor.calibration_date
            existing.calibration_offset = sensor.calibration_offset
            existing.calibration_slope = sensor.calibration_slope
            existing.is_active = sensor.is_active
            existing.status = sensor.status
            existing.manufacturer = sensor.manufacturer
            existing.model = sensor.model
            existing.serial_number = sensor.serial_number
            existing.calibration_expiry = sensor.calibration_expiry
            existing.health_status = sensor.health_status
            existing.battery_level_pct = sensor.battery_level_pct
            existing.last_communication_at = sensor.last_communication_at
        else:
            orm = SensorRegistryORM(
                sensor_id=sensor.sensor_id,
                farm_id=sensor.farm_id,
                pond_id=sensor.pond_id,
                sensor_type=sensor.sensor_type,
                protocol=sensor.protocol.value,
                device_address=sensor.device_address,
                register_map_json=json.dumps(sensor.register_map),
                capabilities_json=json.dumps(sensor.capabilities),
                has_integrated_temp=sensor.has_integrated_temp,
                calibration_date=sensor.calibration_date,
                calibration_offset=sensor.calibration_offset,
                calibration_slope=sensor.calibration_slope,
                is_active=sensor.is_active,
                status=sensor.status,
                manufacturer=sensor.manufacturer,
                model=sensor.model,
                serial_number=sensor.serial_number,
                calibration_expiry=sensor.calibration_expiry,
                health_status=sensor.health_status,
                battery_level_pct=sensor.battery_level_pct,
                last_communication_at=sensor.last_communication_at,
            )
            self._session.add(orm)

        self._session.commit()
        return sensor

    def get(self, sensor_id: str) -> Optional[SensorMetadata]:
        orm = (
            self._session.query(SensorRegistryORM)
            .filter(SensorRegistryORM.sensor_id == sensor_id)
            .first()
        )
        if not orm:
            return None
        return self._to_domain(orm)

    def list_by_pond(self, farm_id: str, pond_id: str) -> List[SensorMetadata]:
        orms = (
            self._session.query(SensorRegistryORM)
            .filter(SensorRegistryORM.farm_id == farm_id, SensorRegistryORM.pond_id == pond_id)
            .order_by(SensorRegistryORM.sensor_id)
            .all()
        )
        return [self._to_domain(o) for o in orms]

    def list_all(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        sensor_type: Optional[str] = None,
        health_status: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[SensorMetadata]:
        query = self._session.query(SensorRegistryORM).filter(SensorRegistryORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(SensorRegistryORM.pond_id == pond_id)
        if sensor_type:
            query = query.filter(SensorRegistryORM.sensor_type == sensor_type)
        if health_status:
            query = query.filter(SensorRegistryORM.health_status == health_status)
        if is_active is not None:
            query = query.filter(SensorRegistryORM.is_active == is_active)
        orms = query.order_by(SensorRegistryORM.pond_id, SensorRegistryORM.sensor_id).all()
        return [self._to_domain(o) for o in orms]

    def record_calibration(
        self,
        farm_id: str,
        pond_id: str,
        sensor_id: str,
        calibration_type: str,
        pre_val: float,
        ref_val: float,
        post_val: float,
        offset: float,
        slope: float,
        technician_id: str,
        valid_until: datetime,
        notes: Optional[str] = None,
    ) -> SensorCalibrationHistoryORM:
        history = SensorCalibrationHistoryORM(
            farm_id=farm_id,
            pond_id=pond_id,
            sensor_id=sensor_id,
            calibration_type=calibration_type,
            pre_calibration_value=pre_val,
            reference_value=ref_val,
            post_calibration_value=post_val,
            calibration_offset=offset,
            calibration_slope=slope,
            technician_id=technician_id,
            notes=notes,
            valid_until=valid_until,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(history)

        sensor = (
            self._session.query(SensorRegistryORM)
            .filter(SensorRegistryORM.sensor_id == sensor_id)
            .first()
        )
        if sensor:
            sensor.calibration_offset = offset
            sensor.calibration_slope = slope
            sensor.calibration_date = datetime.now(timezone.utc)
            sensor.calibration_expiry = valid_until
            sensor.health_status = "HEALTHY"
            sensor.status = "ONLINE"

        self._session.commit()
        return history

    def get_calibration_history(self, sensor_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = (
            self._session.query(SensorCalibrationHistoryORM)
            .filter(SensorCalibrationHistoryORM.sensor_id == sensor_id)
            .order_by(SensorCalibrationHistoryORM.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "farm_id": r.farm_id,
                "pond_id": r.pond_id,
                "sensor_id": r.sensor_id,
                "calibration_type": r.calibration_type,
                "pre_calibration_value": r.pre_calibration_value,
                "reference_value": r.reference_value,
                "post_calibration_value": r.post_calibration_value,
                "calibration_offset": r.calibration_offset,
                "calibration_slope": r.calibration_slope,
                "technician_id": r.technician_id,
                "notes": r.notes,
                "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def record_maintenance(
        self,
        farm_id: str,
        sensor_id: str,
        maintenance_type: str,
        performed_by: str,
        details: Optional[str] = None,
    ) -> SensorMaintenanceLogORM:
        log = SensorMaintenanceLogORM(
            farm_id=farm_id,
            sensor_id=sensor_id,
            maintenance_type=maintenance_type,
            performed_by=performed_by,
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(log)
        self._session.commit()
        return log

    def get_maintenance_logs(self, sensor_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = (
            self._session.query(SensorMaintenanceLogORM)
            .filter(SensorMaintenanceLogORM.sensor_id == sensor_id)
            .order_by(SensorMaintenanceLogORM.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "farm_id": r.farm_id,
                "sensor_id": r.sensor_id,
                "maintenance_type": r.maintenance_type,
                "performed_by": r.performed_by,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def get_stale_sensors(self, farm_id: str, timeout_seconds: int = 180) -> List[SensorMetadata]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        orms = (
            self._session.query(SensorRegistryORM)
            .filter(
                SensorRegistryORM.farm_id == farm_id,
                SensorRegistryORM.is_active == True,
            )
            .all()
        )
        stale = []
        for o in orms:
            last_comm = o.last_communication_at or o.last_reading_at
            if last_comm is None or (last_comm.tzinfo and last_comm < cutoff) or (not last_comm.tzinfo and last_comm < cutoff.replace(tzinfo=None)):
                stale.append(self._to_domain(o))
        return stale

    def seed_defaults_for_pond(self, farm_id: str, pond_id: str) -> None:
        """Seed standard industrial sensor probe suite for a pond if none exist."""
        existing = self.list_by_pond(farm_id, pond_id)
        if existing:
            return

        now = datetime.now(timezone.utc)
        exp = now + timedelta(days=30)

        # 1. Optical DO probe with integrated PT1000 temperature
        do_sensor = SensorMetadata(
            sensor_id=f"{pond_id}-do-opt-01",
            farm_id=farm_id,
            pond_id=pond_id,
            sensor_type="OPTICAL_DO",
            protocol=SensorProtocolType.MODBUS_RTU,
            device_address=1,
            register_map={"do_mg_l": 0, "temperature_c": 2},
            capabilities=["dissolved_oxygen", "temperature"],
            has_integrated_temp=True,
            status="ONLINE",
            manufacturer="AquaSensors Ltd",
            model="AQ-DO-LUM-200",
            serial_number=f"AQ-DO-{pond_id.upper()}",
            calibration_date=now,
            calibration_expiry=exp,
            health_status="HEALTHY",
            battery_level_pct=100.0,
            last_communication_at=now,
        )
        # 2. Industrial pH probe
        ph_sensor = SensorMetadata(
            sensor_id=f"{pond_id}-ph-ind-01",
            farm_id=farm_id,
            pond_id=pond_id,
            sensor_type="PH",
            protocol=SensorProtocolType.MODBUS_RTU,
            device_address=2,
            register_map={"ph": 0},
            capabilities=["ph"],
            has_integrated_temp=False,
            status="ONLINE",
            manufacturer="AquaSensors Ltd",
            model="AQ-PH-IND-400",
            serial_number=f"AQ-PH-{pond_id.upper()}",
            calibration_date=now,
            calibration_expiry=exp,
            health_status="HEALTHY",
            battery_level_pct=100.0,
            last_communication_at=now,
        )
        # 3. Toroidal Salinity probe
        sal_sensor = SensorMetadata(
            sensor_id=f"{pond_id}-sal-cond-01",
            farm_id=farm_id,
            pond_id=pond_id,
            sensor_type="SALINITY",
            protocol=SensorProtocolType.MODBUS_RTU,
            device_address=3,
            register_map={"salinity_ppt": 0},
            capabilities=["salinity"],
            has_integrated_temp=False,
            status="ONLINE",
            manufacturer="AquaSensors Ltd",
            model="AQ-SAL-TOR-600",
            serial_number=f"AQ-SAL-{pond_id.upper()}",
            calibration_date=now,
            calibration_expiry=exp,
            health_status="HEALTHY",
            battery_level_pct=100.0,
            last_communication_at=now,
        )
        # 4. Hydrostatic Water Level probe
        level_sensor = SensorMetadata(
            sensor_id=f"{pond_id}-level-hydro-01",
            farm_id=farm_id,
            pond_id=pond_id,
            sensor_type="WATER_LEVEL",
            protocol=SensorProtocolType.MODBUS_RTU,
            device_address=4,
            register_map={"water_level_meters": 0},
            capabilities=["water_level"],
            has_integrated_temp=False,
            status="ONLINE",
            manufacturer="AquaSensors Ltd",
            model="AQ-LVL-HYD-800",
            serial_number=f"AQ-LVL-{pond_id.upper()}",
            calibration_date=now,
            calibration_expiry=exp,
            health_status="HEALTHY",
            battery_level_pct=100.0,
            last_communication_at=now,
        )

        for s in (do_sensor, ph_sensor, sal_sensor, level_sensor):
            self.register(s)

    def _to_domain(self, orm: SensorRegistryORM) -> SensorMetadata:
        return SensorMetadata(
            sensor_id=orm.sensor_id,
            farm_id=orm.farm_id,
            pond_id=orm.pond_id,
            sensor_type=orm.sensor_type,
            protocol=SensorProtocolType(orm.protocol),
            device_address=orm.device_address,
            register_map=json.loads(orm.register_map_json or "{}"),
            capabilities=json.loads(orm.capabilities_json or "[]"),
            has_integrated_temp=bool(orm.has_integrated_temp),
            calibration_date=orm.calibration_date,
            calibration_offset=orm.calibration_offset or 0.0,
            calibration_slope=orm.calibration_slope or 1.0,
            is_active=bool(orm.is_active),
            status=orm.status or "ONLINE",
            manufacturer=orm.manufacturer or "AquaSensors Ltd",
            model=orm.model or "AQ-PROBE-485",
            serial_number=orm.serial_number,
            calibration_expiry=orm.calibration_expiry,
            health_status=orm.health_status or "HEALTHY",
            battery_level_pct=orm.battery_level_pct if orm.battery_level_pct is not None else 100.0,
            last_communication_at=orm.last_communication_at,
        )
