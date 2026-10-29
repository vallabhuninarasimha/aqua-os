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
        if not transformer_id:
            return TransformerPowerStatus(
                transformer_id="UNCONFIGURED",
                farm_id=farm_id,
                name="Unassigned Feeder",
                capacity_kw=0.0,
                continuous_rating_80pct_kw=0.0,
                current_load_kw=0.0,
                headroom_kw=0.0,
                running_aerator_count=0,
                overload_warning=False,
                capacity_status="UNCONFIGURED",
                load_confidence="UNKNOWN",
                headroom_confidence="UNCONFIGURED",
                is_field_verified=False,
            )

        # Check configured transformer rating
        tx_cfg = None
        if self._farm_config and self._farm_config.transformers:
            for t in self._farm_config.transformers:
                if t.transformer_id == transformer_id:
                    tx_cfg = t
                    break

        if tx_cfg:
            capacity_kw = tx_cfg.capacity_kw
            name = tx_cfg.name
            capacity_status = "CONFIGURED_RATING"
            cont_pct = tx_cfg.max_continuous_load_pct
        elif transformer_id in ("tx-1", "tx-2"):
            capacity_kw = 23.0
            name = "Transformer 1 (North/East Ponds)" if transformer_id == "tx-1" else "Transformer 2 (South/West Ponds)"
            capacity_status = "CONFIGURED_RATING"
            cont_pct = 80.0
        else:
            capacity_kw = 0.0
            name = f"Unconfigured Feeder ({transformer_id})"
            capacity_status = "UNCONFIGURED"
            cont_pct = 0.0

        aerators = self._aerator_repo.list_by_transformer(transformer_id)
        running_aerators = [
            a for a in aerators if a.verified_physical_state == PhysicalRunningState.RUNNING
        ]
        has_unknown_aerator_state = any(
            a.verified_physical_state == PhysicalRunningState.UNKNOWN for a in aerators
        )
        running_count = len(running_aerators)

        # Calculate current load: sum of active power or running_count * rating
        aerator_load = 0.0
        measured_units = 0
        missing_rating_units = 0

        for a in running_aerators:
            if a.power_kw > 0:
                aerator_load += a.power_kw
                measured_units += 1
            elif a.rating_kw > 0:
                aerator_load += a.rating_kw
            else:
                missing_rating_units += 1

        current_load = aerator_load

        # Include pumps assigned to this transformer if running
        running_pumps = []
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
            for p in running_pumps:
                if p.power_kw is not None and p.power_kw > 0:
                    current_load += p.power_kw
                    measured_units += 1
                elif p.rating_kw is not None and p.rating_kw > 0:
                    current_load += p.rating_kw
                else:
                    missing_rating_units += 1
        except Exception:
            pass

        current_load = round(current_load, 2)
        total_running_equipment = running_count + len(running_pumps)

        # Determine load confidence
        if capacity_status == "UNCONFIGURED":
            load_confidence = "UNKNOWN"
        elif has_unknown_aerator_state:
            load_confidence = "UNVERIFIED_EQUIPMENT_STATE"
        elif missing_rating_units > 0:
            load_confidence = "PARTIAL_UNCONFIGURED_RATINGS"
        elif total_running_equipment == 0:
            load_confidence = "IDLE_ESTIMATE"
        elif measured_units == total_running_equipment:
            load_confidence = "MEASURED_EQUIPMENT_SUM"
        else:
            load_confidence = "NAMEPLATE_ESTIMATE"

        if capacity_status == "UNCONFIGURED" or capacity_kw <= 0:
            continuous_80pct = 0.0
            headroom_kw = 0.0
            headroom_confidence = "UNCONFIGURED"
            overload_warning = False
        else:
            continuous_80pct = round(capacity_kw * (cont_pct / 100.0), 2)
            headroom_kw = max(0.0, round(continuous_80pct - current_load, 2))
            headroom_confidence = "THEORETICAL_ESTIMATE"
            overload_warning = current_load >= continuous_80pct

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
            capacity_status=capacity_status,
            load_confidence=load_confidence,
            headroom_confidence=headroom_confidence,
            is_field_verified=False,
            headroom_disclaimer=(
                "Theoretical calculation (80% continuous rating minus estimated equipment load). "
                "Not confirmed field utility capacity."
            ),
        )

    def get_farm_power_summary(self, farm_id: str) -> List[TransformerPowerStatus]:
        """Return load and headroom status for both dedicated 23 kW transformers."""
        # Farm has 2 dedicated 23 kW transformers (tx-1 and tx-2)
        transformer_ids = ["tx-1", "tx-2"]
        return [self.get_transformer_status(farm_id, tx_id) for tx_id in transformer_ids]

