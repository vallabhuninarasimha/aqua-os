"""Domain layer interfaces and protocols for Aqua OS."""

from datetime import datetime
from typing import Dict, List, Optional, Protocol, Tuple

from packages.telemetry_schema.config import PondConfig
from packages.telemetry_schema.models import (
    PondTelemetryPacket,
    SafetyEvaluationResult,
)


class IPondRepository(Protocol):
    """Abstract storage contract for pond configurations.

    Enforces farm-scoped identification to prevent multi-farm collisions.
    """

    def get(self, farm_id: str, pond_id: str) -> Optional[PondConfig]:
        """Retrieve pond configuration by compound key (farm_id, pond_id)."""
        ...

    def list(self, farm_id: Optional[str] = None) -> List[PondConfig]:
        """List ponds, optionally filtered by farm_id."""
        ...

    def save(self, pond: PondConfig) -> PondConfig:
        """Insert or update a pond configuration."""
        ...

    def delete(self, farm_id: str, pond_id: str) -> bool:
        """Delete pond configuration."""
        ...

    def count(self, farm_id: Optional[str] = None, active_only: bool = False) -> int:
        """Count ponds."""
        ...


class ITelemetryRepository(Protocol):
    """Abstract storage contract for sensor telemetry."""

    def save(
        self,
        packet: PondTelemetryPacket,
        evaluation: Optional[SafetyEvaluationResult] = None,
    ) -> None:
        """Persist a telemetry packet (both historical and latest state)."""
        ...

    def get_latest(
        self,
        farm_id: str,
        pond_id: str,
    ) -> Optional[Tuple[PondTelemetryPacket, Optional[SafetyEvaluationResult]]]:
        """Retrieve latest telemetry and evaluation for a specific pond."""
        ...

    def get_all_latest(self, farm_id: str) -> Dict[str, PondTelemetryPacket]:
        """Retrieve latest telemetry packets for all ponds on a farm."""
        ...

    def get_all_latest_with_evaluations(
        self, farm_id: str
    ) -> Dict[str, Tuple[PondTelemetryPacket, Optional[SafetyEvaluationResult]]]:
        """Retrieve latest telemetry packet and evaluation for all ponds on a farm."""
        ...

    def get_history(
        self,
        farm_id: str,
        pond_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[PondTelemetryPacket]:
        """Retrieve historical telemetry packets for a pond within a time window."""
        ...

    def total_ingested_count(self) -> int:
        """Return total number of ingested telemetry packets."""
        ...


class ISafetyEvaluator(Protocol):
    """Abstract domain contract for biological safety and threshold evaluation."""

    def evaluate(
        self,
        packet: PondTelemetryPacket,
        pond_config: Optional[PondConfig],
    ) -> SafetyEvaluationResult:
        """Evaluate water parameters against pond limits and return advisory result."""
        ...
