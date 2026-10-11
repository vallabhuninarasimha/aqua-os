"""In-process simulator background runner service for local demonstration."""

import asyncio
import logging
from typing import Dict, Optional

from apps.api.src.config import settings
from apps.api.src.domain.safety import ThresholdSafetyEvaluator
from apps.api.src.infrastructure.database import SessionLocal
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import (
    SQLTelemetryRepository,
)
from apps.api.src.services.telemetry_broadcaster import broadcaster
from tools.simulators.clock import SystemClock
from tools.simulators.generator import PondTelemetryGenerator
from tools.simulators.scenarios import PondScenarioConfig, ScenarioType

logger = logging.getLogger(__name__)


class LocalSimulatorService:
    """Manages an embedded background telemetry generator for local-first testing."""

    def __init__(self) -> None:
        self.clock = SystemClock()
        self.generator = PondTelemetryGenerator(
            farm_id=settings.default_farm_id,
            pond_count=20,
            clock=self.clock,
            seed=42,
        )
        self.safety_evaluator = ThresholdSafetyEvaluator()
        self.interval_seconds: float = 3.0
        self.is_running: bool = False
        self.step_count: int = 0
        self._task: Optional[asyncio.Task] = None
        self._active_scenarios: Dict[str, str] = {}

    def get_status(self) -> dict:
        """Return operational status of the embedded simulator."""
        return {
            "is_running": self.is_running,
            "interval_seconds": self.interval_seconds,
            "step_count": self.step_count,
            "pond_count": 20,
            "farm_id": settings.default_farm_id,
            "active_scenarios": self._active_scenarios,
        }

    def start(self, interval_seconds: float = 3.0) -> bool:
        """Start background simulation task."""
        if self.is_running:
            return False

        self.interval_seconds = interval_seconds
        self.is_running = True
        self._task = asyncio.create_task(self._simulation_loop())
        logger.info("Simulator background loop started (interval=%.1fs)", self.interval_seconds)
        return True

    def stop(self) -> bool:
        """Stop background simulation task."""
        if not self.is_running:
            return False

        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("Simulator background loop stopped.")
        return True

    def set_scenario(
        self,
        pond_id: str,
        scenario_type: ScenarioType,
        duration_hours: float = 6.0,
    ) -> None:
        """Inject or clear a scenario on a specific pond."""
        if scenario_type == ScenarioType.NORMAL_DIURNAL:
            self.generator.clear_pond_scenario(pond_id)
            self._active_scenarios.pop(pond_id, None)
        else:
            config = PondScenarioConfig(
                pond_id=pond_id,
                scenario_type=scenario_type,
                duration_hours=duration_hours,
            )
            self.generator.set_pond_scenario(pond_id, config)
            self._active_scenarios[pond_id] = scenario_type.value

    def reset_all_scenarios(self) -> None:
        """Reset all ponds to normal biological operation."""
        for pond_id in list(self._active_scenarios.keys()):
            self.generator.clear_pond_scenario(pond_id)
        self._active_scenarios.clear()

    async def step_once(self) -> int:
        # Compute hydrology flow rates based on intake pump and outlet states
        water_flow_rates: Dict[str, Dict[str, float]] = {}
        with SessionLocal() as session:
            try:
                from apps.api.src.infrastructure.repositories.sql_water_repository import SQLWaterRepository
                water_repo = SQLWaterRepository(session)
                pump_info = water_repo.get_pump(farm_id=settings.default_farm_id)
                pump_running = bool(pump_info and pump_info.get("physical_state") == "RUNNING")
                
                # Check active water exchanges or outlet positions
                outlets = water_repo.list_pond_outlet_statuses(farm_id=settings.default_farm_id)
                for o in outlets:
                    p_id = o.get("pond_id")
                    if not p_id:
                        continue
                    inflow = 0.0
                    drain = 0.0

                    # If pump is running in simulated dry-run, deliver ~0.04 m/hr inflow
                    if pump_running:
                        inflow = 0.04

                    # If normal outlet is open, overflow discharge occurs (~0.03 m/hr)
                    if o.get("normal_outlet_state") == "OPEN":
                        drain += 0.03

                    # If full-drain monk is unlocked and open, emergency drain occurs (~0.15 m/hr)
                    if not o.get("full_drain_locked") and o.get("full_drain_outlet_state") == "OPEN":
                        drain += 0.15

                    if inflow > 0.0 or drain > 0.0:
                        water_flow_rates[p_id] = {
                            "inflow_rate_m_per_hr": inflow,
                            "drain_rate_m_per_hr": drain,
                        }
            except Exception as e:
                logger.debug("Hydraulic rate query error (safe fallback to 0.0): %s", e)

        packets = self.generator.step(
            dt_seconds=self.interval_seconds,
            water_flow_rates=water_flow_rates,
        )
        self.step_count += 1

        with SessionLocal() as session:
            pond_repo = SQLPondRepository(session)
            telemetry_repo = SQLTelemetryRepository(session)

            for packet in packets:
                pond_config = pond_repo.get(farm_id=packet.farm_id, pond_id=packet.pond_id)
                evaluation = self.safety_evaluator.evaluate(
                    packet=packet, pond_config=pond_config
                )
                telemetry_repo.save(packet=packet, evaluation=evaluation)

                # Broadcast incremental update to dashboard clients
                await broadcaster.broadcast(
                    "pond_update",
                    {
                        "farm_id": packet.farm_id,
                        "pond_id": packet.pond_id,
                        "packet": packet.model_dump(mode="json"),
                        "evaluation": evaluation.model_dump(mode="json"),
                    },
                )

        # Broadcast cycle completion
        await broadcaster.broadcast(
            "simulator_cycle",
            {
                "step_count": self.step_count,
                "pond_count": len(packets),
                "active_scenarios": self._active_scenarios,
            },
        )
        return len(packets)

    async def _simulation_loop(self) -> None:
        """Continuous background execution loop."""
        try:
            while self.is_running:
                await self.step_once()
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Simulator encountered loop error: %s", e)
            self.is_running = False


# Global singleton instance for local runtime
simulator_service = LocalSimulatorService()
