"""Simulated Sensor Adapter for testing and edge runtime emulation."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from apps.api.src.domain.hardware_interfaces import (
    ISensorAdapter,
    RawSensorSample,
    SensorMetadata,
    SensorProtocolType,
)
from packages.telemetry_schema.models import MetricType


class SimulatedSensorAdapter(ISensorAdapter):
    """Adapter for virtualized/simulated pond sensors."""

    def __init__(self) -> None:
        pass

    def get_capabilities(self, metadata: SensorMetadata) -> List[MetricType]:
        caps: List[MetricType] = []
        for c in metadata.capabilities:
            try:
                caps.append(MetricType(c))
            except ValueError:
                pass
        return caps

    def is_healthy(self, sensor_id: str) -> bool:
        return True

    def read_metrics(
        self,
        metadata: SensorMetadata,
        simulated_values: Optional[Dict[str, float]] = None,
    ) -> List[RawSensorSample]:
        now = datetime.now(timezone.utc)
        vals = simulated_values or {}
        samples: List[RawSensorSample] = []

        for metric_name, val in vals.items():
            try:
                m_type = MetricType(metric_name)
                samples.append(
                    RawSensorSample(
                        sensor_id=metadata.sensor_id,
                        metric_type=m_type,
                        raw_value=val,
                        calibrated_value=val,
                        unit="",
                        timestamp=now,
                        is_valid=True,
                    )
                )
            except ValueError:
                continue

        return samples

