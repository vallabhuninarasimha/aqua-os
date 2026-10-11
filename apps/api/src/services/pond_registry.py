"""Pond Registry Service.

Maintains in-memory configuration-driven state of all farm ponds.
Initialized with 20 ponds by default, extensible to N ponds at runtime.
"""

from typing import List, Optional

from packages.telemetry_schema.config import (
    FarmConfig,
    PondConfig,
    get_default_20_pond_farm_config,
)


class PondRegistryService:
    """Manages pond metadata, thresholds, and active status."""

    def __init__(self, farm_id: str = "farm-alpha") -> None:
        self._farm: FarmConfig = get_default_20_pond_farm_config(farm_id=farm_id)

    @property
    def farm(self) -> FarmConfig:
        return self._farm

    def get_all_ponds(self) -> List[PondConfig]:
        """Return list of all configured ponds sorted by pond_id."""
        return sorted(self._farm.ponds.values(), key=lambda p: p.pond_id)

    def get_pond(self, pond_id: str) -> Optional[PondConfig]:
        """Retrieve single pond by ID."""
        return self._farm.get_pond(pond_id)

    def register_or_update_pond(self, pond: PondConfig) -> PondConfig:
        """Add a new pond or update existing pond configuration dynamically."""
        self._farm.add_or_update_pond(pond)
        return pond

    def get_active_pond_count(self) -> int:
        return self._farm.active_pond_count()

    def get_total_pond_count(self) -> int:
        return len(self._farm.ponds)


# Singleton instance for the modular monolith
pond_registry = PondRegistryService()
