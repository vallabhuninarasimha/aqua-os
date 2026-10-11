"""Aqua OS Simulation Tooling.

Provides a reproducible, multi-pond biological & physical sensor simulator
with virtual clock injection and configurable scenarios.
"""

from .clock import IClock, SystemClock, VirtualClock
from .generator import PondTelemetryGenerator
from .physics import PondPhysicsModel, PondPhysicsState
from .scenarios import PondScenarioConfig, ScenarioType

__all__ = [
    "IClock",
    "SystemClock",
    "VirtualClock",
    "PondPhysicsModel",
    "PondPhysicsState",
    "ScenarioType",
    "PondScenarioConfig",
    "PondTelemetryGenerator",
]

