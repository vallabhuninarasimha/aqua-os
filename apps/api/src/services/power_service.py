"""Power monitoring service for farm electrical infrastructure.

Tracks electrical load, continuous 80% ratings (18.4 kW on 23 kW transformers),
headroom, and running equipment across transformers.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.hardware_interfaces import (
    IPowerMonitoringAdapter,
    PhysicalRunningState,
    TransformerPowerStatus,
)
from apps.api.src.infrastructure.repositories.sql_aerator_repository import SQLAeratorRepository
from packages.telemetry_schema.config import FarmConfig, TransformerConfig, get_farm_6acre_8pond_config


class PowerMonitoringService(IPowerMonitoringAdapter):
    """Monitors transformer loads against 23 kW dedicated capacity with 80% continuous rating."""

    def __init__(self, session: Session, farm_config: Optional[FarmConfig] = None) -> None:
        self._session = session
        self._aerator_repo = SQLAeratorRepository(session)
        # Default to 2x 23 kW transformers if not specified
        self._farm_config = farm_config

    def get_transformer_status(self, farm_id: str, transformer_id: str) -> TransformerPowerStatus:
        aerators = self._aerator_repo.list_by_transformer(transformer_id)
        running_aerators = [
            a for a in aerators if a.verified_physical_state == PhysicalRunningState.RUNNING
        ]
        running_count = len(running_aerators)
        
        # Calculate current load: sum of active power or running_count * rating
        current_load = sum(
            a.power_kw if a.power_kw > 0 else a.rating_kw for a in running_aerators
        )

        # Include pumps assigned to this transformer if running
        try:
            from apps.api.src.infrastructure.models import WaterPumpORM
            running_pumps = (
                self._session.query(WaterPumpORM)
                .filter(
                    WaterPumpORM.farm_id == farm_id,
                    WaterPumpORM.transformer_id == transformer_id,
                    WaterPumpORM.physical_state == "RUNNING",
                )
                .all()
            )
            current_load += sum(
                (p.power_kw if (p.power_kw is not None and p.power_kw > 0) else (p.rating_kw or 0.0))
                for p in running_pumps
            )
        except Exception:
            pass

        current_load = round(current_load, 2)

        # 23 kW capacity, 80% continuous limit = 18.4 kW
        capacity_kw = 23.0
        continuous_80pct = round(capacity_kw * 0.80, 2)  # 18.4 kW
        headroom_kw = max(0.0, round(continuous_80pct - current_load, 2))
        overload_warning = current_load >= continuous_80pct

        name = "Transformer 1 (North/East Ponds)" if transformer_id == "tx-1" else "Transformer 2 (South/West Ponds)"

        return TransformerPowerStatus(
            transformer_id=transformer_id,
            farm_id=farm_id,
            name=name,
            capacity_kw=capacity_kw,
            continuous_rating_80pct_kw=continuous_80pct,
            current_load_kw=current_load,
            headroom_kw=headroom_kw,
            running_aerator_count=running_count,
            overload_warning=overload_warning,
        )

    def get_farm_power_summary(self, farm_id: str) -> List[TransformerPowerStatus]:
        """Return load and headroom status for both dedicated 23 kW transformers."""
        # Farm has 2 dedicated 23 kW transformers (tx-1 and tx-2)
        transformer_ids = ["tx-1", "tx-2"]
        return [self.get_transformer_status(farm_id, tx_id) for tx_id in transformer_ids]

