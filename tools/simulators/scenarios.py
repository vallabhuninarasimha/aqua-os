"""Simulation scenarios and failure-mode configurations."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ScenarioType(str, Enum):
    """Supported simulation scenarios for operational validation."""

    NORMAL_DIURNAL = "NORMAL_DIURNAL"
    AERATOR_FAILURE = "AERATOR_FAILURE"
    SUDDEN_HYPOXIA = "SUDDEN_HYPOXIA"
    SENSOR_FAULT = "SENSOR_FAULT"
    PROBE_FOULING = "PROBE_FOULING"
    STALE_READINGS = "STALE_READINGS"
    OUT_OF_BOUNDS_SPIKE = "OUT_OF_BOUNDS_SPIKE"
    WATER_LEAK = "WATER_LEAK"
    OVERFLOW_RISK = "OVERFLOW_RISK"


@dataclass
class PondScenarioConfig:
    """Configuration assigning a scenario and schedule to a simulated pond."""

    pond_id: str
    scenario_type: ScenarioType = ScenarioType.NORMAL_DIURNAL
    trigger_hour: Optional[float] = None  # Hour of day (0-24) to activate fault
    duration_hours: float = 4.0           # Duration of the fault condition
    severity_multiplier: float = 1.0

