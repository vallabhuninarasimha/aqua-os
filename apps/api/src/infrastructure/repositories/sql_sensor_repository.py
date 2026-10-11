"""SQL repository for physical and logical sensor metadata."""

import json
from typing import List, Optional

from sqlalchemy.orm import Session

from apps.api.src.domain.hardware_interfaces import (
    ISensorRegistry,
    SensorMetadata,
    SensorProtocolType,
)
from apps.api.src.infrastructure.models import SensorRegistryORM


class SQLSensorRepository(ISensorRegistry):
    """SQL-backed storage for sensor probe hardware registry."""

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

    def seed_defaults_for_pond(self, farm_id: str, pond_id: str) -> None:
        """Seed standard industrial sensor probe suite for a pond if none exist."""
        existing = self.list_by_pond(farm_id, pond_id)
        if existing:
            return

        # 1. Optical DO probe with integrated PT1000 temperature (re-uses temp reading)
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
            is_active=orm.is_active,
            status=orm.status or "ONLINE",
        )

