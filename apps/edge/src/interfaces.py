"""Abstract interfaces and protocol definitions for sovereign Edge Controllers."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple

from packages.telemetry_schema.config import PondConfig
from packages.telemetry_schema.models import (
    MetricReading,
    MetricType,
    PondTelemetryPacket,
    SafetyEvaluationResult,
)


class ProvenanceType(str, Enum):
    """Data provenance distinguishing physical hardware readings from biophysical simulations."""
    SIMULATED = "SIMULATED"
    FIELD_MEASURED = "FIELD_MEASURED"


class ActuatorExecutionMode(str, Enum):
    """Execution mode for actuator commands."""
    DRY_RUN = "DRY_RUN"
    PHYSICAL_COMMISSIONED = "PHYSICAL_COMMISSIONED"


class ActuatorExecutionResult(Protocol):
    """Feedback structure confirming actuator state change."""
    command_id: str
    actuator_id: str
    desired_state: str
    verified_state: str
    is_success: bool
    current_amps: float
    error_message: Optional[str]
    executed_at: datetime


class ISensorAdapter(Protocol):
    """Adapter reading physical Modbus/RS485 probes or simulated telemetry generators."""

    def read_telemetry(self, pond_id: str) -> PondTelemetryPacket:
        """Poll physical or simulated probes, apply calibration slopes/offsets, and return packet."""
        ...

    def is_probe_online(self, sensor_id: str) -> bool:
        """Verify transducer responsiveness and signal integrity."""
        ...

    def get_provenance(self) -> ProvenanceType:
        """Return whether adapter produces physical measurements or simulated readings."""
        ...


class IActuatorAdapter(Protocol):
    """Adapter for operating pond aerators and water pumps with physical feedback verification."""

    def execute_command(
        self,
        command_id: str,
        actuator_id: str,
        actuator_type: str,
        target_state: str,
        max_duration_seconds: int = 300,
        mode: ActuatorExecutionMode = ActuatorExecutionMode.DRY_RUN,
    ) -> Dict[str, Any]:
        """Dispatch command to physical MCC contactor or dry-run simulation envelope."""
        ...

    def verify_contactor_feedback(self, actuator_id: str) -> str:
        """Query physical auxiliary contact or simulated running confirmation ('RUNNING', 'STOPPED', 'FAULT')."""
        ...

    def emergency_stop_all(self, reason: str = "EMERGENCY_STOP_TRIGGERED") -> bool:
        """Hardware/firmware master interlock tripping all motor contactors immediately."""
        ...


class ILocalStorage(Protocol):
    """Local crash-resilient storage engine utilizing SQLite WAL mode."""

    def save_telemetry_and_enqueue(
        self,
        packet: PondTelemetryPacket,
        evaluation: SafetyEvaluationResult,
    ) -> str:
        """Persist telemetry locally and enqueue for cloud synchronization."""
        ...

    def get_pending_sync_batch(self, limit: int = 50) -> List[Tuple[str, PondTelemetryPacket]]:
        """Retrieve unsynced telemetry packets from local queue."""
        ...

    def mark_synced(self, idempotency_hashes: List[str]) -> None:
        """Mark enqueued packets as successfully delivered."""
        ...

    def save_local_alert(
        self,
        pond_id: str,
        severity: str,
        metric: str,
        message: str,
        reading_value: float,
    ) -> int:
        """Record sovereign local alert independent of cloud availability."""
        ...

    def get_queue_depth(self) -> int:
        """Return number of pending outbound telemetry packets."""
        ...


class ILocalSafetyEvaluator(Protocol):
    """Sovereign safety evaluation engine executing directly on edge gateway hardware."""

    def evaluate(
        self,
        packet: PondTelemetryPacket,
        pond_config: Optional[PondConfig] = None,
    ) -> SafetyEvaluationResult:
        """Deterministic biological threshold and hypoxia risk evaluation."""
        ...

    def check_aeration_interlocks(
        self,
        pond_id: str,
        current_do_mg_l: float,
        proposed_action: str,
    ) -> Tuple[bool, str]:
        """Validate whether starting or stopping aerators violates local safety rules."""
        ...

