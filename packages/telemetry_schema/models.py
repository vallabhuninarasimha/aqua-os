"""Core data contracts and telemetry schemas for Aqua OS.

These models define data transfer contracts for edge-to-cloud ingestion,
actuation safety bounds, hardware heartbeats, and analytical processing.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MetricType(str, Enum):
    """Standardized physical and biochemical metrics in shrimp ponds."""

    DISSOLVED_OXYGEN = "dissolved_oxygen"  # mg/L or ppm
    TEMPERATURE = "temperature"            # Celsius
    PH = "ph"                              # pH scale 0-14
    SALINITY = "salinity"                  # ppt (parts per thousand)
    ORP = "orp"                            # mV (Oxidation Reduction Potential)
    WATER_LEVEL = "water_level"            # meters
    BATTERY_VOLTAGE = "battery_voltage"    # Volts DC
    MAINS_VOLTAGE = "mains_voltage"        # Volts AC
    CURRENT_AMPERES = "current_amperes"    # Amperes AC/DC
    POWER_KW = "power_kw"                  # Active Power Kilowatts


class QualityStatus(str, Enum):
    """Data quality classification for sensor telemetry."""

    GOOD = "GOOD"
    SUSPECT_DRIFT = "SUSPECT_DRIFT"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    SENSOR_FAULT = "SENSOR_FAULT"
    CALIBRATING = "CALIBRATING"


class AlertSeverity(str, Enum):
    """Operational alert urgency classifications."""

    NORMAL = "NORMAL"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


SeverityLevel = AlertSeverity


class ActuatorType(str, Enum):
    """Physical farm equipment types."""

    AERATOR_PADDLEWHEEL = "aerator_paddlewheel"
    AERATOR_ASPIRATOR = "aerator_aspirator"
    FEEDER_AUTO = "feeder_auto"
    WATER_PUMP = "water_pump"
    PROBIOTIC_DOSER = "probiotic_doser"


class ActuatorState(str, Enum):
    """Operating states for physical equipment."""

    OFF = "OFF"
    ON = "ON"
    FAULT = "FAULT"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


# Physical sanity boundaries for sensor validation
PHYSICAL_BOUNDS: Dict[MetricType, tuple[float, float, str]] = {
    MetricType.DISSOLVED_OXYGEN: (0.0, 25.0, "mg/L"),
    MetricType.TEMPERATURE: (0.0, 50.0, "°C"),
    MetricType.PH: (0.0, 14.0, "pH"),
    MetricType.SALINITY: (0.0, 60.0, "ppt"),
    MetricType.ORP: (-1000.0, 1000.0, "mV"),
    MetricType.WATER_LEVEL: (0.0, 5.0, "m"),
    MetricType.BATTERY_VOLTAGE: (0.0, 30.0, "V"),
    MetricType.MAINS_VOLTAGE: (0.0, 500.0, "V"),
    MetricType.CURRENT_AMPERES: (0.0, 150.0, "A"),
    MetricType.POWER_KW: (0.0, 100.0, "kW"),
}


class MetricReading(BaseModel):
    """An individual sensor reading with unit, quality, and physical bounds checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_type: MetricType = Field(..., description="Type of metric measured")
    value: float = Field(..., description="Numeric sensor value")
    unit: str = Field(..., description="Unit of measurement (e.g., mg/L, °C, ppt)")
    quality: QualityStatus = Field(
        default=QualityStatus.GOOD,
        description="Data quality status after edge filtering",
    )
    raw_adc: Optional[int] = Field(
        default=None,
        description="Raw analog-to-digital converter integer for diagnostics",
    )

    @model_validator(mode="after")
    def validate_physical_bounds(self) -> "MetricReading":
        bounds = PHYSICAL_BOUNDS.get(self.metric_type)
        if bounds:
            min_val, max_val, expected_unit = bounds
            if self.value < min_val or self.value > max_val:
                if self.quality == QualityStatus.GOOD:
                    object.__setattr__(self, "quality", QualityStatus.OUT_OF_BOUNDS)
        return self


class HardwareStatus(BaseModel):
    """Diagnostics and power state of the edge/sub-controller node."""

    mains_power_ok: bool = Field(True, description="Mains electricity present")
    battery_level_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    rssi_dbm: Optional[int] = Field(None, description="Signal strength in dBm")
    local_buffer_backlog: int = Field(0, ge=0, description="Unsynced records in local SQLite")
    temperature_internal_c: Optional[float] = Field(None, description="Enclosure temperature")


class PondTelemetryPacket(BaseModel):
    """Standardized telemetry packet transmitted by Edge to Cloud.

    Configured for 20-pond farm baseline and dynamically expandable.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field("1.0", description="Contract version")
    farm_id: str = Field(..., min_length=2, max_length=64, description="Unique farm identifier")
    pond_id: str = Field(..., min_length=2, max_length=64, description="Unique pond identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC sample timestamp",
    )
    metrics: Dict[MetricType, MetricReading] = Field(
        ...,
        description="Map of metric types to validated readings",
    )
    hardware_status: Optional[HardwareStatus] = Field(
        default=None,
        description="Hardware health of the measuring station",
    )
    is_simulated: bool = Field(
        default=False,
        description="Explicit flag marking generated synthetic/simulation data",
    )

    @field_validator("timestamp")
    @classmethod
    def ensure_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ensure_at_least_one_metric(self) -> "PondTelemetryPacket":
        if not self.metrics:
            raise ValueError("Telemetry packet must contain at least one metric reading.")
        return self

    def get_metric_value(self, metric_type: MetricType) -> Optional[float]:
        """Convenience accessor for a metric value if present and good."""
        reading = self.metrics.get(metric_type)
        if reading and reading.quality in (QualityStatus.GOOD, QualityStatus.SUSPECT_DRIFT):
            return reading.value
        return None


class ActuatorCommand(BaseModel):
    """Safety-bounded command to control physical equipment."""

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(..., description="UUID or unique idempotency token")
    farm_id: str = Field(...)
    pond_id: str = Field(...)
    actuator_id: str = Field(...)
    actuator_type: ActuatorType = Field(...)
    target_state: ActuatorState = Field(...)
    max_duration_seconds: int = Field(
        ...,
        ge=1,
        le=28800,
        description="Watchdog auto-off timer (max 8 hours) to prevent runaways",
    )
    reason: str = Field(..., min_length=3, description="Audit reason for actuation")
    issued_by: str = Field(..., description="User ID or AUTOMATED_SAFETY_RULE")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EdgeHeartbeat(BaseModel):
    """Gateway vitality ping for Dead-Man's Watchdog monitoring."""

    model_config = ConfigDict(extra="forbid")

    farm_id: str = Field(...)
    gateway_id: str = Field(...)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uptime_seconds: int = Field(..., ge=0)
    firmware_version: str = Field(...)
    active_ponds_reporting: List[str] = Field(default_factory=list)
    offline_backlog_count: int = Field(0, ge=0)


class SafetyEvaluationResult(BaseModel):
    """Result of real-time telemetry threshold check against pond biological bounds."""

    pond_id: str
    is_safe: bool
    severity: AlertSeverity
    messages: List[str]
    recommended_action: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
