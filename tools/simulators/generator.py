"""20-Pond Telemetry Generator producing validated Aqua OS telemetry packets.

Enforces reproducibility via seedable random number generator and injectable clock.
All output packets are explicitly marked with `is_simulated = True`.
"""

import random
from typing import Dict, List, Optional

from packages.telemetry_schema.models import (
    HardwareStatus,
    MetricReading,
    MetricType,
    PondTelemetryPacket,
    QualityStatus,
)
from tools.simulators.clock import IClock, SystemClock
from tools.simulators.physics import PondPhysicsModel
from tools.simulators.scenarios import PondScenarioConfig, ScenarioType


class PondTelemetryGenerator:
    """Coordinates physics simulation and telemetry packet synthesis across N ponds."""

    def __init__(
        self,
        farm_id: str = "farm-alpha",
        pond_count: int = 20,
        clock: Optional[IClock] = None,
        seed: int = 42,
    ) -> None:
        self.farm_id = farm_id
        self.pond_count = pond_count
        self.clock = clock or SystemClock()
        self._rng = random.Random(seed)

        # Physics models per pond
        self._ponds: Dict[str, PondPhysicsModel] = {}
        # Scenarios per pond
        self._scenarios: Dict[str, PondScenarioConfig] = {}
        # Cache for stale reading scenario
        self._last_readings: Dict[str, Dict[MetricType, float]] = {}

        for i in range(1, pond_count + 1):
            pond_id = f"pond-{i:02d}"
            # Vary initial parameters slightly per pond using seeded RNG
            base_do = 5.5 + self._rng.uniform(-0.4, 0.4)
            base_temp = 28.3 + self._rng.uniform(-0.3, 0.3)
            base_ph = 7.9 + self._rng.uniform(-0.1, 0.1)
            salinity = 25.0 + self._rng.uniform(-1.0, 1.0)
            respiration = 0.42 + self._rng.uniform(-0.05, 0.05)

            self._ponds[pond_id] = PondPhysicsModel(
                base_do=base_do,
                base_temp=base_temp,
                base_ph=base_ph,
                salinity_ppt=salinity,
                shrimp_respiration_rate=respiration,
            )
            self._scenarios[pond_id] = PondScenarioConfig(
                pond_id=pond_id,
                scenario_type=ScenarioType.NORMAL_DIURNAL,
            )

    def set_pond_scenario(self, pond_id: str, scenario: PondScenarioConfig) -> None:
        """Assign a scenario to a specific pond."""
        if pond_id in self._ponds:
            self._scenarios[pond_id] = scenario

    def clear_pond_scenario(self, pond_id: str) -> None:
        """Reset a pond scenario back to normal diurnal cycle."""
        if pond_id in self._ponds:
            self._scenarios[pond_id] = PondScenarioConfig(
                pond_id=pond_id,
                scenario_type=ScenarioType.NORMAL_DIURNAL,
            )

    def step(
        self,
        dt_seconds: float = 10.0,
        water_flow_rates: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> List[PondTelemetryPacket]:
        """Advance simulation by dt_seconds and return a telemetry packet for each pond.
        
        Optional `water_flow_rates` may provide per-pond physical flow dynamics:
        {pond_id: {"inflow_rate_m_per_hr": float, "drain_rate_m_per_hr": float}}
        """
        current_time = self.clock.now()
        hour_of_day = (
            current_time.hour
            + (current_time.minute / 60.0)
            + (current_time.second / 3600.0)
        )
        packets: List[PondTelemetryPacket] = []

        for pond_id, physics in self._ponds.items():
            scenario = self._scenarios[pond_id]

            # Determine if scenario fault is active
            fault_active = False
            if scenario.trigger_hour is not None:
                end_hour = (scenario.trigger_hour + scenario.duration_hours) % 24.0
                if scenario.trigger_hour <= end_hour:
                    fault_active = scenario.trigger_hour <= hour_of_day <= end_hour
                else:
                    # Overnight wrap-around
                    fault_active = hour_of_day >= scenario.trigger_hour or hour_of_day <= end_hour
            elif scenario.scenario_type != ScenarioType.NORMAL_DIURNAL:
                fault_active = True

            aerator_override = None
            plankton_dieoff = False
            bod_spike = 0.0

            # Default hydraulic rates from water management or 0.0
            pond_flows = (water_flow_rates or {}).get(pond_id, {})
            inflow_rate = pond_flows.get("inflow_rate_m_per_hr", 0.0)
            drain_rate = pond_flows.get("drain_rate_m_per_hr", 0.0)
            leak_rate = 0.0
            rainfall_rate = 0.0

            if fault_active:
                if scenario.scenario_type == ScenarioType.AERATOR_FAILURE:
                    aerator_override = False
                elif scenario.scenario_type == ScenarioType.SUDDEN_HYPOXIA:
                    plankton_dieoff = True
                    bod_spike = 1.4 * scenario.severity_multiplier
                elif scenario.scenario_type == ScenarioType.WATER_LEAK:
                    # Simulated bund seepage or valve failure causing rapid water drop (e.g. 0.08 m/hr)
                    leak_rate = 0.08 * scenario.severity_multiplier
                elif scenario.scenario_type == ScenarioType.OVERFLOW_RISK:
                    # Simulated heavy monsoon downpour / unchecked inflow causing overflow risk
                    rainfall_rate = 0.07 * scenario.severity_multiplier

            # Step physical body forward
            state = physics.step(
                dt_seconds=dt_seconds,
                timestamp=current_time,
                aerator_override=aerator_override,
                plankton_dieoff=plankton_dieoff,
                sudden_bod_spike=bod_spike,
                inflow_rate_m_per_hr=inflow_rate,
                drain_rate_m_per_hr=drain_rate,
                leak_rate_m_per_hr=leak_rate,
                rainfall_rate_m_per_hr=rainfall_rate,
            )

            # Measurement noise (Gaussian)
            noise_do = self._rng.gauss(0.0, 0.04)
            noise_temp = self._rng.gauss(0.0, 0.06)
            noise_ph = self._rng.gauss(0.0, 0.02)
            noise_sal = self._rng.gauss(0.0, 0.05)
            noise_wl = self._rng.gauss(0.0, 0.003)

            measured_do = max(0.0, state.dissolved_oxygen_mg_l + noise_do)
            measured_temp = state.temperature_c + noise_temp
            measured_ph = state.ph + noise_ph
            measured_sal = state.salinity_ppt + noise_sal
            measured_wl = max(0.0, state.water_level_m + noise_wl)

            do_quality = QualityStatus.GOOD
            wl_quality = QualityStatus.GOOD

            # Apply sensor failure scenarios
            if fault_active:
                if scenario.scenario_type == ScenarioType.SENSOR_FAULT:
                    do_quality = QualityStatus.SENSOR_FAULT
                    wl_quality = QualityStatus.SENSOR_FAULT
                    measured_do = 0.0  # Or disconnected line value
                    measured_wl = 0.0
                elif scenario.scenario_type == ScenarioType.PROBE_FOULING:
                    do_quality = QualityStatus.SUSPECT_DRIFT
                    # Negative measurement bias from biofilm insulation
                    measured_do = max(0.2, measured_do * 0.72)
                elif scenario.scenario_type == ScenarioType.OUT_OF_BOUNDS_SPIKE:
                    # Electrical spike exceeding physical bounds
                    measured_do = 32.5
                    measured_wl = 5.8
                elif scenario.scenario_type == ScenarioType.STALE_READINGS:
                    # Re-use previous frozen value without noise
                    if pond_id in self._last_readings:
                        measured_do = self._last_readings[pond_id][MetricType.DISSOLVED_OXYGEN]
                        measured_temp = self._last_readings[pond_id][MetricType.TEMPERATURE]
                        measured_ph = self._last_readings[pond_id][MetricType.PH]
                        measured_wl = self._last_readings[pond_id].get(MetricType.WATER_LEVEL, measured_wl)

            # Cache readings
            self._last_readings[pond_id] = {
                MetricType.DISSOLVED_OXYGEN: measured_do,
                MetricType.TEMPERATURE: measured_temp,
                MetricType.PH: measured_ph,
                MetricType.SALINITY: measured_sal,
                MetricType.WATER_LEVEL: measured_wl,
            }

            metrics = {
                MetricType.DISSOLVED_OXYGEN: MetricReading(
                    metric_type=MetricType.DISSOLVED_OXYGEN,
                    value=round(measured_do, 2),
                    unit="mg/L",
                    quality=do_quality,
                ),
                MetricType.TEMPERATURE: MetricReading(
                    metric_type=MetricType.TEMPERATURE,
                    value=round(measured_temp, 2),
                    unit="°C",
                    quality=QualityStatus.GOOD,
                ),
                MetricType.PH: MetricReading(
                    metric_type=MetricType.PH,
                    value=round(measured_ph, 2),
                    unit="pH",
                    quality=QualityStatus.GOOD,
                ),
                MetricType.SALINITY: MetricReading(
                    metric_type=MetricType.SALINITY,
                    value=round(measured_sal, 2),
                    unit="ppt",
                    quality=QualityStatus.GOOD,
                ),
                MetricType.WATER_LEVEL: MetricReading(
                    metric_type=MetricType.WATER_LEVEL,
                    value=round(measured_wl, 3),
                    unit="m",
                    quality=wl_quality,
                ),
            }

            mains_ok = not (
                fault_active and scenario.scenario_type == ScenarioType.AERATOR_FAILURE
            )
            hw_status = HardwareStatus(
                mains_power_ok=mains_ok,
                battery_level_pct=94.0,
                rssi_dbm=-68,
                local_buffer_backlog=0,
            )

            packet = PondTelemetryPacket(
                farm_id=self.farm_id,
                pond_id=pond_id,
                timestamp=current_time,
                metrics=metrics,
                hardware_status=hw_status,
                is_simulated=True,  # Clearly tagged as simulated
            )
            packets.append(packet)

        return packets
