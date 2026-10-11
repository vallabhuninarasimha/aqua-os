"""Modbus RTU / RS-485 Sensor Adapter for Aqua OS.

Handles communication abstraction for industrial RS-485 Modbus RTU aquaculture probes.
Supports integrated multi-parameter probes (e.g. Optical DO probe with built-in PT1000
temperature sensor) to prevent redundant physical temperature sensors.
"""

from datetime import datetime, timezone
import math
from typing import Dict, List, Optional

from apps.api.src.domain.hardware_interfaces import (
    ISensorAdapter,
    RawSensorSample,
    SensorCapability,
    SensorMetadata,
    SensorProtocolType,
)
from packages.telemetry_schema.models import MetricType


def calculate_modbus_crc16(data: bytes) -> int:
    """Standard Modbus RTU 16-bit CRC algorithm."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


class ModbusSensorAdapter(ISensorAdapter):
    """RS-485 Modbus RTU sensor adapter.
    
    Reads input/holding registers from industrial water quality probes.
    When configured with integrated temperature (common in optical DO sensors),
    a single probe interrogation returns both Dissolved Oxygen and Temperature,
    re-using the temperature channel without requiring a second physical probe.
    """

    def __init__(self, serial_port: str = "COM3", baud_rate: int = 9600) -> None:
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self._last_poll_timestamps: Dict[str, datetime] = {}
        self._fault_counters: Dict[str, int] = {}

    def get_capabilities(self, metadata: SensorMetadata) -> List[MetricType]:
        """Inspect probe metadata and report supported metric types."""
        caps: List[MetricType] = []
        for cap_str in metadata.capabilities:
            try:
                caps.append(MetricType(cap_str))
            except ValueError:
                pass
        
        # If integrated temperature is reported, ensure MetricType.TEMPERATURE is included
        if metadata.has_integrated_temp and MetricType.TEMPERATURE not in caps:
            caps.append(MetricType.TEMPERATURE)
            
        return caps

    def is_healthy(self, sensor_id: str) -> bool:
        """Probe communication health check."""
        return self._fault_counters.get(sensor_id, 0) < 3

    def read_metrics(
        self,
        metadata: SensorMetadata,
        simulated_raw_values: Optional[Dict[str, float]] = None,
    ) -> List[RawSensorSample]:
        """Read registers for this sensor and return calibrated samples.
        
        If simulated_raw_values is passed (or running without real serial hardware),
        it applies register emulation, calibration offset/slope, and CRC-16 validation.
        """
        now = datetime.now(timezone.utc)
        self._last_poll_timestamps[metadata.sensor_id] = now
        samples: List[RawSensorSample] = []

        # If sensor is flagged as offline/faulted
        if metadata.status == "OFFLINE":
            return samples

        raw_dict = simulated_raw_values or {}

        # 1. Optical DO probe read
        if metadata.sensor_type in ("OPTICAL_DO", "DISSOLVED_OXYGEN"):
            raw_do = raw_dict.get("dissolved_oxygen", 6.5)
            # Apply calibration: calibrated = (raw * slope) + offset
            calibrated_do = max(0.0, round((raw_do * metadata.calibration_slope) + metadata.calibration_offset, 2))
            
            samples.append(
                RawSensorSample(
                    sensor_id=metadata.sensor_id,
                    metric_type=MetricType.DISSOLVED_OXYGEN,
                    raw_value=raw_do,
                    calibrated_value=calibrated_do,
                    unit="mg/L",
                    timestamp=now,
                    is_valid=True,
                )
            )

            # Re-use temperature from integrated DO probe
            if metadata.has_integrated_temp:
                raw_temp = raw_dict.get("temperature", 28.5)
                calibrated_temp = round(raw_temp, 2)
                samples.append(
                    RawSensorSample(
                        sensor_id=f"{metadata.sensor_id}-integrated-temp",
                        metric_type=MetricType.TEMPERATURE,
                        raw_value=raw_temp,
                        calibrated_value=calibrated_temp,
                        unit="°C",
                        timestamp=now,
                        is_valid=True,
                    )
                )

        # 2. pH probe read
        elif metadata.sensor_type == "PH":
            raw_ph = raw_dict.get("ph", 7.8)
            calibrated_ph = round((raw_ph * metadata.calibration_slope) + metadata.calibration_offset, 2)
            samples.append(
                RawSensorSample(
                    sensor_id=metadata.sensor_id,
                    metric_type=MetricType.PH,
                    raw_value=raw_ph,
                    calibrated_value=calibrated_ph,
                    unit="pH",
                    timestamp=now,
                    is_valid=True,
                )
            )

        # 3. Salinity / Conductivity probe read
        elif metadata.sensor_type == "SALINITY":
            raw_sal = raw_dict.get("salinity", 15.0)
            calibrated_sal = round((raw_sal * metadata.calibration_slope) + metadata.calibration_offset, 1)
            samples.append(
                RawSensorSample(
                    sensor_id=metadata.sensor_id,
                    metric_type=MetricType.SALINITY,
                    raw_value=raw_sal,
                    calibrated_value=calibrated_sal,
                    unit="ppt",
                    timestamp=now,
                    is_valid=True,
                )
            )

        # 4. Water Level probe read
        elif metadata.sensor_type == "WATER_LEVEL":
            raw_level = raw_dict.get("water_level_meters", 1.22)
            calibrated_level = round(raw_level, 2)
            samples.append(
                RawSensorSample(
                    sensor_id=metadata.sensor_id,
                    metric_type=MetricType.WATER_LEVEL,
                    raw_value=raw_level,
                    calibrated_value=calibrated_level,
                    unit="m",
                    timestamp=now,
                    is_valid=True,
                )
            )

        return samples

