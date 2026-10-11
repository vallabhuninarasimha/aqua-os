"""Hardware abstraction interfaces and domain contracts for Aqua OS.

Defines protocols for sensors (Modbus/RS485), aerator controllers,
power monitoring, sensor registries, and alert lifecycles.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Union
from pydantic import BaseModel, Field

from packages.telemetry_schema.models import MetricType, SeverityLevel


class SensorProtocolType(str, Enum):
    MODBUS_RTU = "modbus_rtu"
    MODBUS_TCP = "modbus_tcp"
    ANALOG_4_20MA = "analog_4_20ma"
    SIMULATED = "simulated"


class SensorCapability(str, Enum):
    DISSOLVED_OXYGEN = "dissolved_oxygen"
    TEMPERATURE = "temperature"
    PH = "ph"
    SALINITY = "salinity"
    ORP = "orp"
    WATER_LEVEL = "water_level"


class SensorMetadata(BaseModel):
    """Metadata describing a physical or simulated sensor probe."""
    sensor_id: str
    farm_id: str
    pond_id: str
    sensor_type: str
    protocol: SensorProtocolType = SensorProtocolType.MODBUS_RTU
    device_address: int = 1
    register_map: Dict[str, int] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    has_integrated_temp: bool = False
    calibration_date: Optional[datetime] = None
    calibration_offset: float = 0.0
    calibration_slope: float = 1.0
    is_active: bool = True
    status: str = "ONLINE"  # ONLINE, FAULTED, OFFLINE, CALIBRATING


class RawSensorSample(BaseModel):
    """Sample returned by a physical sensor adapter before domain normalization."""
    sensor_id: str
    metric_type: MetricType
    raw_value: float
    calibrated_value: float
    unit: str
    timestamp: datetime
    is_valid: bool = True
    error_code: Optional[str] = None


class DesiredEquipmentState(str, Enum):
    AUTO = "AUTO"
    FORCE_ON = "FORCE_ON"
    FORCE_OFF = "FORCE_OFF"
    OFF = "OFF"


class PhysicalRunningState(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    TRIPPED = "TRIPPED"
    UNKNOWN = "UNKNOWN"


class AeratorStatus(BaseModel):
    """Status model distinguishing desired command state from verified physical state."""
    aerator_id: str
    pond_id: str
    transformer_id: str
    rating_kw: float = 1.5
    desired_state: DesiredEquipmentState = DesiredEquipmentState.AUTO
    verified_physical_state: PhysicalRunningState = PhysicalRunningState.STOPPED
    current_draw_amps: float = 0.0
    power_kw: float = 0.0
    runtime_minutes_today: float = 0.0
    last_state_change: Optional[datetime] = None
    fault_reason: Optional[str] = None


class AerationDecisionResult(BaseModel):
    """Safe pond-specific aeration decision record (dry-run evaluation)."""
    decision_id: str
    farm_id: str
    pond_id: str
    timestamp: datetime
    do_value_mg_l: Optional[float]
    do_sensor_healthy: bool
    proposed_action: str  # "START", "STOP", "HOLD"
    reason: str
    interlocks_ok: bool
    transformer_headroom_kw: float
    execution_mode: str = "DRY_RUN"  # Always DRY_RUN in this phase
    operator_id: Optional[str] = None
    risk_level: str = "NORMAL"  # "NORMAL", "MODERATE", "CRITICAL", "UNKNOWN"
    is_simulated: bool = True
    sensor_freshness_seconds: Optional[float] = None
    manual_override_active: bool = False


class TransformerPowerStatus(BaseModel):
    """Electrical supply and load status for a dedicated farm transformer."""
    transformer_id: str
    farm_id: str
    name: str
    capacity_kw: float
    continuous_rating_80pct_kw: float
    current_load_kw: float
    headroom_kw: float
    running_aerator_count: int
    overload_warning: bool = False


# ============================================================================
# Protocol Definitions
# ============================================================================

class ISensorAdapter(Protocol):
    """Interface for sensor adapters (Modbus RTU, 4-20mA, Simulated)."""

    def read_metrics(self, metadata: SensorMetadata) -> List[RawSensorSample]:
        """Poll physical registers or simulated generator and return samples."""
        ...

    def get_capabilities(self, metadata: SensorMetadata) -> List[MetricType]:
        """Return list of metric types provided by this physical sensor."""
        ...

    def is_healthy(self, sensor_id: str) -> bool:
        """Check probe communication health and response latency."""
        ...


class ISensorRegistry(Protocol):
    """Storage and lookup contract for physical/logical sensor probes."""

    def register(self, sensor: SensorMetadata) -> SensorMetadata:
        """Register or update a sensor."""
        ...

    def get(self, sensor_id: str) -> Optional[SensorMetadata]:
        """Fetch metadata by sensor_id."""
        ...

    def list_by_pond(self, farm_id: str, pond_id: str) -> List[SensorMetadata]:
        """List all sensors installed in a specific pond."""
        ...


class IAeratorController(Protocol):
    """Contract for safe pond aeration state machine and decision evaluation."""

    def evaluate_pond(
        self,
        farm_id: str,
        pond_id: str,
        current_do_mg_l: Optional[float],
        sensor_healthy: bool,
    ) -> AerationDecisionResult:
        """Run aeration state machine in DRY_RUN mode with anti-cycling hysteresis."""
        ...


class IEquipmentStatusProvider(Protocol):
    """Contract for querying verified physical state and power of aerators."""

    def get_aerator_status(self, pond_id: str) -> List[AeratorStatus]:
        """Get status of all aerators in pond."""
        ...

    def update_physical_status(
        self,
        aerator_id: str,
        physical_state: PhysicalRunningState,
        current_draw_amps: float,
        power_kw: float,
    ) -> AeratorStatus:
        """Record verified physical feedback from power meter/current CT."""
        ...


class IPowerMonitoringAdapter(Protocol):
    """Contract for farm transformer electrical monitoring."""

    def get_transformer_status(self, farm_id: str, transformer_id: str) -> TransformerPowerStatus:
        """Query transformer current load and 80% continuous rating headroom."""
        ...

    def get_farm_power_summary(self, farm_id: str) -> List[TransformerPowerStatus]:
        """Query all transformers for the farm."""
        ...


class IAlertService(Protocol):
    """Contract for alert lifecycle management (ACTIVE, ACKNOWLEDGED, RESOLVED)."""

    def raise_or_update(
        self,
        farm_id: str,
        pond_id: str,
        alert_code: str,
        severity: SeverityLevel,
        message: str,
        recommended_action: Optional[str] = None,
    ) -> Any:
        """Raise new alert or update existing active alert deduplicating entries."""
        ...

    def acknowledge(self, alert_id: str, acknowledged_by: str) -> Optional[Any]:
        """Transition alert to ACKNOWLEDGED."""
        ...

    def resolve(self, alert_id: str, resolved_by: str) -> Optional[Any]:
        """Transition alert to RESOLVED."""
        ...

    def get_active_alerts(self, farm_id: str, pond_id: Optional[str] = None) -> List[Any]:
        """List active and acknowledged alerts."""
        ...

