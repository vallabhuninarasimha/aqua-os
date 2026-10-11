"""Simulator management routes for local testing and demonstration."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.src.security.dependencies import require_permission
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.simulator_service import simulator_service
from tools.simulators.scenarios import ScenarioType

router = APIRouter(prefix="/simulator", tags=["Simulator"])


class SimulatorControlRequest(BaseModel):
    interval_seconds: float = Field(default=3.0, ge=0.5, le=60.0)


class ScenarioInjectionRequest(BaseModel):
    pond_id: str = Field(..., min_length=2, max_length=64)
    scenario_type: ScenarioType
    duration_hours: float = Field(default=6.0, ge=0.1, le=48.0)


@router.get("/status")
async def get_simulator_status(
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
) -> dict:
    """Retrieve operational status and active scenarios of the embedded simulator."""
    return simulator_service.get_status()


@router.post("/start", status_code=status.HTTP_200_OK)
async def start_simulator(
    body: Optional[SimulatorControlRequest] = None,
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
) -> dict:
    """Start continuous local telemetry generation."""
    interval = body.interval_seconds if body else 3.0
    started = simulator_service.start(interval_seconds=interval)
    return {
        "started": started,
        "message": (
            f"Simulator running at {interval}s interval"
            if started
            else "Simulator already running"
        ),
        "status": simulator_service.get_status(),
    }


@router.post("/stop", status_code=status.HTTP_200_OK)
async def stop_simulator(
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
) -> dict:
    """Stop continuous local telemetry generation."""
    stopped = simulator_service.stop()
    return {
        "stopped": stopped,
        "message": "Simulator paused" if stopped else "Simulator already idle",
        "status": simulator_service.get_status(),
    }


@router.post("/step", status_code=status.HTTP_200_OK)
async def step_simulator(
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
) -> dict:
    """Advance simulation by 1 step manually."""
    pond_count = await simulator_service.step_once()
    return {
        "ponds_generated": pond_count,
        "step_count": simulator_service.step_count,
    }


@router.post("/scenario", status_code=status.HTTP_200_OK)
async def inject_scenario(
    body: ScenarioInjectionRequest,
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
) -> dict:
    """Inject a failure or biological anomaly into a specific pond."""
    try:
        simulator_service.set_scenario(
            pond_id=body.pond_id,
            scenario_type=body.scenario_type,
            duration_hours=body.duration_hours,
        )
        return {
            "message": f"Scenario '{body.scenario_type.value}' injected on '{body.pond_id}'",
            "active_scenarios": simulator_service._active_scenarios,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to inject scenario: {e}",
        )


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_scenarios(
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
) -> dict:
    """Reset all ponds back to normal biological state."""
    simulator_service.reset_all_scenarios()
    return {
        "message": "All ponds reset to normal biological parameters",
        "active_scenarios": {},
    }
