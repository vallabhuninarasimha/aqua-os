"""Pond physical and biochemical simulation model.

NOTE: This physical model is designed for software integration, resilience testing,
and failure-mode validation. It is NOT scientifically validated for commercial aquaculture research.
"""

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PondPhysicsState:
    """Current continuous state of simulated water body."""

    dissolved_oxygen_mg_l: float
    temperature_c: float
    ph: float
    salinity_ppt: float
    aerator_active: bool = True
    water_level_m: float = 1.22


class PondPhysicsModel:
    """Simulates water parameter dynamics across day/night cycles."""

    def __init__(
        self,
        base_do: float = 6.0,
        base_temp: float = 28.5,
        base_ph: float = 7.9,
        salinity_ppt: float = 25.0,
        shrimp_respiration_rate: float = 0.45,  # mg/L per hour
        base_water_level: float = 1.22,
    ) -> None:
        self.state = PondPhysicsState(
            dissolved_oxygen_mg_l=base_do,
            temperature_c=base_temp,
            ph=base_ph,
            salinity_ppt=salinity_ppt,
            aerator_active=True,
            water_level_m=base_water_level,
        )
        self.shrimp_respiration_rate = shrimp_respiration_rate

    def step(
        self,
        dt_seconds: float,
        timestamp: datetime,
        aerator_override: bool | None = None,
        plankton_dieoff: bool = False,
        sudden_bod_spike: float = 0.0,
        inflow_rate_m_per_hr: float = 0.0,
        drain_rate_m_per_hr: float = 0.0,
        leak_rate_m_per_hr: float = 0.0,
        rainfall_rate_m_per_hr: float = 0.0,
    ) -> PondPhysicsState:
        """Step the physics state forward by dt_seconds."""
        dt_hours = dt_seconds / 3600.0
        hour_of_day = timestamp.hour + (timestamp.minute / 60.0) + (timestamp.second / 3600.0)

        # 1. Daylight and Solar Radiation Curve
        # Daylight between 06:00 and 18:00; peak at 12:30
        if 6.0 <= hour_of_day <= 18.0 and not plankton_dieoff:
            sun_angle = math.sin(math.pi * (hour_of_day - 6.0) / 12.0)
            photosynthesis_rate = 1.6 * max(0.0, sun_angle)  # mg/L/hr O2 produced
        else:
            photosynthesis_rate = 0.0

        # 2. Respiration (biomass + sediment + algae night respiration)
        night_resp = 0.5 if not (6.0 <= hour_of_day <= 18.0) else 0.1
        respiration_rate = self.shrimp_respiration_rate + night_resp
        respiration_rate += sudden_bod_spike

        # 3. Aeration Contribution
        if aerator_override is not None:
            self.state.aerator_active = aerator_override

        # Saturation DO approximation at given temp and salinity
        # Henry's Law approximation: ~7.2 mg/L at 28°C and 25 ppt
        do_sat = (
            7.2
            - 0.08 * (self.state.temperature_c - 28.0)
            - 0.03 * (self.state.salinity_ppt - 25.0)
        )

        if self.state.aerator_active:
            # High reaeration transfer coefficient when paddlewheels turn
            k_la = 1.2  # hr^-1
        else:
            # Low passive surface transfer when aerators are off
            k_la = 0.08

        reaeration_rate = k_la * (do_sat - self.state.dissolved_oxygen_mg_l)

        # Net DO change
        d_do = (photosynthesis_rate - respiration_rate + reaeration_rate) * dt_hours
        self.state.dissolved_oxygen_mg_l = max(
            0.0, min(22.0, self.state.dissolved_oxygen_mg_l + d_do)
        )

        # 4. Temperature Diurnal Cycle (trough at 05:30, peak at 14:30)
        temp_cycle = math.sin(2.0 * math.pi * (hour_of_day - 8.5) / 24.0)
        target_temp = 28.5 + 2.2 * temp_cycle
        self.state.temperature_c += (target_temp - self.state.temperature_c) * min(
            1.0, dt_hours * 1.5
        )

        # 5. pH Diurnal Cycle (CO2 uptake increases pH in afternoon, respiration drops it at night)
        if plankton_dieoff:
            target_ph = 7.4
        else:
            ph_cycle = math.sin(2.0 * math.pi * (hour_of_day - 8.0) / 24.0)
            target_ph = 7.95 + 0.35 * ph_cycle
        self.state.ph += (target_ph - self.state.ph) * min(1.0, dt_hours * 1.2)

        # 6. Water Level Dynamics (Evaporation, Inflow, Drainage, Rainfall, Seepage/Leaks)
        # Baseline natural pan evaporation ~6mm/day (~0.00025 m/hr), heightened during midday warmth
        temp_factor = max(0.5, (self.state.temperature_c - 20.0) / 10.0)
        daylight_factor = 1.4 if (6.0 <= hour_of_day <= 18.0) else 0.6
        evaporation_rate_m_per_hr = 0.00025 * temp_factor * daylight_factor

        net_water_rate = (
            inflow_rate_m_per_hr
            + rainfall_rate_m_per_hr
            - drain_rate_m_per_hr
            - leak_rate_m_per_hr
            - evaporation_rate_m_per_hr
        )
        d_water_level = net_water_rate * dt_hours
        # Clamp to realistic physical pond basin bounds (0.05m to 2.50m)
        self.state.water_level_m = round(
            max(0.05, min(2.50, self.state.water_level_m + d_water_level)), 4
        )

        return self.state
