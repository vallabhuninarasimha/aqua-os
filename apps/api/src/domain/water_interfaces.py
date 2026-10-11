"""Domain contracts, data classes, and protocol interfaces for Water Management."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
from pydantic import BaseModel, Field


class GateState(str, Enum):
    """Hydraulic gate or valve mechanical state."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    PARTIALLY_OPEN = "PARTIALLY_OPEN"
    UNKNOWN = "UNKNOWN"
    FAULT = "FAULT"


class WaterManagementMode(str, Enum):
    """Operational mode for water manipulation."""
    NORMAL_MAINTENANCE = "NORMAL_MAINTENANCE"
    EXCHANGE_INFLOW = "EXCHANGE_INFLOW"
    EXCHANGE_LEVELING = "EXCHANGE_LEVELING"
    HARVEST_DRAIN = "HARVEST_DRAIN"
    EMERGENCY_OVERFLOW = "EMERGENCY_OVERFLOW"


class PumpOperationalState(str, Enum):
    """Physical running state of intake/transfer pump."""
    OFF = "OFF"
    RUNNING = "RUNNING"
    FAULT = "FAULT"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class WaterPumpInfo(BaseModel):
    """Pump unit configuration and verified electrical/running state."""
    pump_id: str
    farm_id: str
    name: str = "River Intake Pump House"
    motor_hp: Optional[float] = None
    rating_kw: Optional[float] = None
    transformer_id: Optional[str] = None
    desired_state: str = "OFF"
    physical_state: PumpOperationalState = PumpOperationalState.OFF
    current_draw_amps: float = 0.0
    power_kw: float = 0.0
    last_run_timestamp: Optional[datetime] = None
    is_configured: bool = False


class PondOutletStatus(BaseModel):
    """Pond-specific dual-outlet configuration, targets, and lock status."""
    pond_id: str
    farm_id: str
    water_level_target_m: float = 1.22  # Provisional: nominal 4.0 ft, pending pond bathymetry
    water_level_min_m: float = 0.95     # Provisional: nominal 3.1 ft, pending survey
    water_level_max_m: float = 1.40     # Provisional: nominal 4.6 ft, pending freeboard survey
    limits_provisional: bool = True
    current_level_m: Optional[float] = None
    is_level_stale: bool = False
    normal_outlet_state: GateState = GateState.CLOSED
    full_drain_outlet_state: GateState = GateState.CLOSED
    full_drain_locked: bool = True
    drain_lock_reason: str = "Active batch biological containment"
    physical_position_confirmed: bool = False
    software_intent_only: bool = True


class PumpAdvisoryDecision(BaseModel):
    """Dry-run evaluated recommendation for intake pump operation."""
    proposed_action: str  # "START", "STOP", "HOLD"
    pump_id: str
    target_pond_id: Optional[str] = None
    reason: str
    transformer_id: str
    transformer_headroom_kw: float
    interlocks_ok: bool
    execution_mode: str = "DRY_RUN"  # Real actuator control strictly disabled
    operator_id: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WaterExchangeRecord(BaseModel):
    """Log entry for water level adjustments, exchanges, or drainage."""
    exchange_id: str
    farm_id: str
    pond_id: str
    mode: WaterManagementMode
    initial_level_m: float
    final_level_m: Optional[float] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    operator_id: str
    notes: Optional[str] = None


class IWaterRepository(Protocol):
    """Protocol interface for water management domain persistence."""

    def get_pump(self, farm_id: str, pump_id: str = "pump-river-intake-01") -> Optional[Dict[str, Any]]:
        """Fetch intake pump details."""
        ...

    def list_pumps(self, farm_id: str) -> List[Dict[str, Any]]:
        """List all pumps belonging to a farm."""
        ...

    def update_pump_config(
        self,
        farm_id: str,
        pump_id: str,
        transformer_id: str,
        motor_hp: Optional[float] = None,
        rating_kw: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update configurable pump specs and electrical transformer assignment."""
        ...

    def update_pump_state(
        self,
        farm_id: str,
        pump_id: str,
        desired_state: str,
        physical_state: str,
        current_draw_amps: float = 0.0,
        power_kw: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """Update running electrical measurements and desired command state."""
        ...

    def get_pond_outlet_status(self, farm_id: str, pond_id: str) -> Optional[Dict[str, Any]]:
        """Get dual outlet positions, lock status, and level targets for a pond."""
        ...

    def list_pond_outlet_statuses(self, farm_id: str) -> List[Dict[str, Any]]:
        """List outlet statuses across all configured ponds."""
        ...

    def update_pond_outlet_state(
        self,
        farm_id: str,
        pond_id: str,
        normal_outlet_state: Optional[str] = None,
        full_drain_outlet_state: Optional[str] = None,
        full_drain_locked: Optional[bool] = None,
        drain_lock_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update mechanical outlet gates and lock state."""
        ...

    def update_pond_level_targets(
        self,
        farm_id: str,
        pond_id: str,
        target_m: float,
        min_m: float,
        max_m: float,
    ) -> Optional[Dict[str, Any]]:
        """Update configurable target depth and safe level boundaries."""
        ...

    def log_water_exchange(
        self,
        farm_id: str,
        pond_id: str,
        mode: str,
        initial_level_m: float,
        operator_id: str,
        final_level_m: Optional[float] = None,
        notes: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record manual or advisory water exchange activity."""
        ...

    def complete_water_exchange(
        self,
        farm_id: str,
        exchange_id: str,
        final_level_m: float,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark an ongoing water exchange as completed."""
        ...

    def list_water_exchange_logs(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List historical exchange and drainage records."""
        ...
