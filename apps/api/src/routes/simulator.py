"""Simulator management routes for local testing and demonstration."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session, get_pond_repository
from apps.api.src.domain.interfaces import IPondRepository
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


# Synthetic profiles are intentionally labelled simulated and must never be shown as physical sensor data.
SIMULATION_DATASETS = {
    "baseline-stable": {
        "label": "Baseline stable pond", "scenario_type": "NORMAL_DIURNAL",
        "description": "Normal diurnal variation for UI, telemetry, and event-history testing.",
        "expected_checks": ["freshness", "trend rendering", "source badge", "no false critical alert"],
    },
    "low-do-event": {
        "label": "Low dissolved oxygen event", "scenario_type": "SUDDEN_HYPOXIA",
        "description": "Synthetic low-oxygen event for alert and advisory workflow testing.",
        "expected_checks": ["risk finding", "operator review", "fresh telemetry verification", "DRY_RUN command record"],
    },
    "sensor-stale": {
        "label": "Stale sensor / communication loss", "scenario_type": "STALE_READINGS",
        "description": "Synthetic stale-reading fault for stale-data handling and fail-safe UI testing.",
        "expected_checks": ["stale flag", "no healthy inference", "command remains dry-run"],
    },
    "aerator-failure": {
        "label": "Aerator failure", "scenario_type": "AERATOR_FAILURE",
        "description": "Synthetic aerator-failure scenario; does not change a physical aerator.",
        "expected_checks": ["failure alert", "pond history correlation", "operator approval", "edge command audit"],
    },
    "probe-fouling": {
        "label": "Probe fouling / biased reading", "scenario_type": "PROBE_FOULING",
        "description": "Synthetic sensor quality anomaly to verify uncertainty handling.",
        "expected_checks": ["sensor-quality warning", "evidence timestamp", "no physical control"],
    },
}


@router.get("/datasets")
async def list_simulation_datasets(
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
) -> dict:
    """List included synthetic sensor datasets/scenarios for safe dry-run testing."""
    return {"data_class": "SIMULATED_NOT_PHYSICAL", "datasets": [{"dataset_id": key, **value} for key, value in SIMULATION_DATASETS.items()],
            "physical_actuation_enabled": False}


class DatasetApplyRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id, min_length=2, max_length=64)
    pond_id: str = Field(..., min_length=2, max_length=64)
    duration_hours: float = Field(default=1.0, ge=0.1, le=24.0)
    start_stream: bool = Field(default=False)
    interval_seconds: float = Field(default=3.0, ge=1.0, le=60.0)


@router.post("/datasets/{dataset_id}/apply")
async def apply_simulation_dataset(
    dataset_id: str,
    body: DatasetApplyRequest,
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    pond_repository: IPondRepository = Depends(get_pond_repository),
) -> dict:
    """Apply a synthetic scenario to one pond; optional stream generates marked simulated telemetry."""
    verify_farm_access(user, body.farm_id)
    if dataset_id not in SIMULATION_DATASETS:
        raise HTTPException(status_code=404, detail="Simulation dataset not found.")
    if body.farm_id != settings.default_farm_id:
        raise HTTPException(status_code=409, detail="Current embedded simulator is configured only for the default farm. No data was generated.")
    if not pond_repository.get(farm_id=body.farm_id, pond_id=body.pond_id):
        raise HTTPException(status_code=404, detail="Pond not found in the selected farm.")
    profile = SIMULATION_DATASETS[dataset_id]
    try:
        scenario = ScenarioType(profile["scenario_type"])
        simulator_service.set_scenario(pond_id=body.pond_id, scenario_type=scenario, duration_hours=body.duration_hours)
        if body.start_stream and not simulator_service.is_running:
            simulator_service.start(interval_seconds=body.interval_seconds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unable to apply simulation profile.") from exc
    return {"dataset_id": dataset_id, "farm_id": body.farm_id, "pond_id": body.pond_id,
            "scenario_type": scenario.value, "duration_hours": body.duration_hours,
            "stream_started_by_request": bool(body.start_stream), "simulator_status": simulator_service.get_status(),
            "data_class": "SIMULATED_NOT_PHYSICAL", "physical_actuation_enabled": False,
            "message": "Synthetic telemetry only. This does not control physical equipment."}
