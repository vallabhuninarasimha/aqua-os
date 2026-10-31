"""Safety-gated edge command interface. This implementation is simulation-only."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session, get_pond_repository, get_telemetry_repository
from apps.api.src.domain.interfaces import IPondRepository, ITelemetryRepository
from apps.api.src.infrastructure.models import AgentDecisionORM, AeratorUnitORM, EdgeCommandORM, WaterPumpORM
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.edge_command_simulation import (
    SIMULATION_FEEDBACK_PROFILES, evaluate_simulated_actuator_command,
)

router = APIRouter(prefix="/edge", tags=["Local Edge Controller"])


class SimulateCommandResultRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id, min_length=2, max_length=64)
    feedback_profile: str = Field(default="NORMAL_FEEDBACK", pattern="^(NORMAL_FEEDBACK|ACTUATOR_STUCK|FEEDBACK_LOST)$")
    max_telemetry_age_seconds: int = Field(default=120, ge=1, le=3600)


class EdgeCommandRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id, min_length=2, max_length=64)
    pond_id: str = Field(..., min_length=2, max_length=64)
    decision_id: str = Field(..., min_length=36, max_length=36)
    actuator_type: str = Field(..., pattern="^(AERATOR|WATER_PUMP)$")
    actuator_id: str = Field(..., min_length=2, max_length=64)
    requested_state: str = Field(..., pattern="^(ON|OFF)$")
    reason: str = Field(..., min_length=3, max_length=1000)
    max_duration_seconds: int = Field(default=300, ge=1, le=1800)
    idempotency_key: Optional[str] = Field(default=None, max_length=64)
    client_timestamp: Optional[datetime] = None


def _as_dict(row: EdgeCommandORM) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    try:
        result = json.loads(row.result_json or "{}")
    except json.JSONDecodeError:
        result = {}
    return {
        "command_id": row.command_id, "farm_id": row.farm_id, "pond_id": row.pond_id,
        "decision_id": row.decision_id, "actuator_type": row.actuator_type,
        "actuator_id": row.actuator_id, "requested_state": row.requested_state,
        "mode": row.mode, "status": row.status, "payload": payload, "result": result,
        "requested_by": row.requested_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "physical_execution_enabled": False,
    }


@router.get("/status")
async def edge_status(
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
) -> dict[str, Any]:
    verify_farm_access(user, farm_id)
    return {
        "farm_id": farm_id, "controller_mode": "SIMULATION_ONLY",
        "online": False, "api_reachable": True, "controller_connected": False,
        "controller_status": "NOT_CONNECTED",
        "physical_execution_enabled": False, "independent_interlock_verified": False,
        "emergency_stop_verified": False, "manual_override_verified": False,
        "command_policy": "APPROVED_DECISION_REQUIRED_DRY_RUN_ONLY",
        "status_note": "The API is reachable; no local edge gateway heartbeat has been verified.",
    }


@router.post("/commands", status_code=201)
async def queue_edge_command(
    request: EdgeCommandRequest,
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    session: Session = Depends(get_db_session),
    pond_repository: IPondRepository = Depends(get_pond_repository),
) -> dict[str, Any]:
    """Record a simulated command request; never write to a physical device."""
    verify_farm_access(user, request.farm_id)
    now = datetime.now(timezone.utc)

    # 1. Command TTL Expiration Check (5 minutes = 300s)
    if request.client_timestamp:
        c_ts = request.client_timestamp if request.client_timestamp.tzinfo else request.client_timestamp.replace(tzinfo=timezone.utc)
        age_seconds = (now - c_ts).total_seconds()
        if age_seconds > 300:
            raise HTTPException(
                status_code=400,
                detail=f"Command expired: Actuator command was generated {age_seconds:.0f}s ago (maximum TTL is 300s). Re-evaluation required.",
            )

    pond = pond_repository.get(farm_id=request.farm_id, pond_id=request.pond_id)
    if not pond:
        raise HTTPException(status_code=404, detail="Pond not found in the selected farm.")
    if request.actuator_type == "AERATOR":
        equipment = session.query(AeratorUnitORM).filter_by(
            farm_id=request.farm_id, pond_id=request.pond_id, aerator_id=request.actuator_id
        ).first()
    else:
        equipment = session.query(WaterPumpORM).filter_by(
            farm_id=request.farm_id, pump_id=request.actuator_id
        ).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Actuator is not registered for this farm/pond.")

    # 2. Idempotency Check
    if request.idempotency_key:
        past_cmds = session.query(EdgeCommandORM).filter_by(
            farm_id=request.farm_id, pond_id=request.pond_id, actuator_id=request.actuator_id
        ).order_by(EdgeCommandORM.created_at.desc()).limit(10).all()
        for cmd in past_cmds:
            try:
                p = json.loads(cmd.payload_json or "{}")
                if p.get("idempotency_key") == request.idempotency_key:
                    return _as_dict(cmd)
            except Exception:
                pass

    # 3. Anti-Rapid-Cycling Lockout Check
    if request.actuator_type == "AERATOR" and hasattr(equipment, "last_state_change") and equipment.last_state_change:
        lsc = equipment.last_state_change if equipment.last_state_change.tzinfo else equipment.last_state_change.replace(tzinfo=timezone.utc)
        cycle_age = (now - lsc).total_seconds()
        if cycle_age < 300 and equipment.desired_state == request.requested_state:
            raise HTTPException(
                status_code=409,
                detail=f"Anti-rapid-cycling lockout active: Aerator '{request.actuator_id}' already in state '{request.requested_state}'. Must wait {int(300 - cycle_age)}s before cycling.",
            )

    decision = session.query(AgentDecisionORM).filter_by(
        decision_id=request.decision_id, farm_id=request.farm_id, pond_id=request.pond_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Approved decision for this pond was not found.")
    if decision.status != "APPROVED":
        raise HTTPException(status_code=409, detail="An approved operator decision is required before a command can be queued.")
    # Reject commands whose finding does not concern an action/issue for this pond.
    try:
        finding = json.loads(decision.finding_snapshot_json or "{}")
    except json.JSONDecodeError:
        finding = {}
    allowed_pond = str(finding.get("pond_id") or decision.pond_id or "")
    if allowed_pond != request.pond_id:
        raise HTTPException(status_code=409, detail="Decision evidence does not match the requested pond.")

    command_id = str(uuid.uuid4())
    payload = {
        "reason": request.reason.strip(), "max_duration_seconds": request.max_duration_seconds,
        "issued_by": user.user_id, "requested_at": now.isoformat(),
        "idempotency_key": request.idempotency_key,
        "simulated": True,
    }
    result = {
        "accepted_for_simulation": True,
        "physical_command_sent": False,
        "desired_state_is_not_physical_confirmation": True,
        "reason": "Physical commissioning gates are not verified; command is recorded only.",
    }
    row = EdgeCommandORM(
        command_id=command_id, farm_id=request.farm_id, pond_id=request.pond_id,
        decision_id=request.decision_id, actuator_type=request.actuator_type,
        actuator_id=request.actuator_id, requested_state=request.requested_state,
        mode="DRY_RUN", status="QUEUED_SIMULATION", payload_json=json.dumps(payload),
        result_json=json.dumps(result), requested_by=user.user_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    try:
        history = json.loads(decision.event_history_json or "[]")
    except json.JSONDecodeError:
        history = []
    history.append({"event": "EDGE_COMMAND_QUEUED_DRY_RUN", "command_id": command_id,
                    "actor_id": user.user_id, "timestamp": datetime.now(timezone.utc).isoformat(),
                    "actuator_type": request.actuator_type, "requested_state": request.requested_state})
    decision.event_history_json = json.dumps(history[-100:])
    decision.updated_by = user.user_id
    decision.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(row)
    return _as_dict(row)


@router.get("/actuator-simulation-profiles")
async def list_actuator_simulation_profiles(
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
) -> dict[str, Any]:
    """Describe feedback-fault profiles for synthetic actuator validation."""
    return {
        "data_class": "SIMULATED_NOT_PHYSICAL",
        "profiles": [{"profile_id": key, "description": value} for key, value in SIMULATION_FEEDBACK_PROFILES.items()],
        "physical_execution_enabled": False,
    }


@router.post("/commands/{command_id}/simulate-result")
async def simulate_edge_command_result(
    command_id: str,
    request: SimulateCommandResultRequest,
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_WRITE)),
    session: Session = Depends(get_db_session),
    telemetry_repository: ITelemetryRepository = Depends(get_telemetry_repository),
) -> dict[str, Any]:
    """Simulate interlock/feedback outcomes for a queued command; never drives hardware."""
    verify_farm_access(user, request.farm_id)
    row = session.query(EdgeCommandORM).filter_by(command_id=command_id, farm_id=request.farm_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Edge command not found.")
    if row.status != "QUEUED_SIMULATION":
        raise HTTPException(status_code=409, detail=f"Command cannot be simulated from status {row.status}.")
    latest = telemetry_repository.get_latest(farm_id=row.farm_id, pond_id=row.pond_id)
    packet, evaluation = latest if latest else (None, None)
    result = evaluate_simulated_actuator_command(
        actuator_type=row.actuator_type,
        requested_state=row.requested_state,
        packet=packet,
        safety_evaluation=evaluation,
        feedback_profile=request.feedback_profile,
        max_telemetry_age_seconds=request.max_telemetry_age_seconds,
    )
    result.update({
        "command_id": row.command_id,
        "farm_id": row.farm_id,
        "pond_id": row.pond_id,
        "actuator_id": row.actuator_id,
        "requested_state": row.requested_state,
        "feedback_profile": request.feedback_profile,
        "physical_execution_enabled": False,
    })
    row.status = result["simulation_status"]
    row.result_json = json.dumps(result, separators=(",", ":"), ensure_ascii=False)
    session.commit()
    session.refresh(row)
    return _as_dict(row)


@router.get("/commands")
async def list_edge_commands(
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    pond_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    verify_farm_access(user, farm_id)
    query = session.query(EdgeCommandORM).filter(EdgeCommandORM.farm_id == farm_id)
    if pond_id:
        query = query.filter(EdgeCommandORM.pond_id == pond_id)
    rows = query.order_by(EdgeCommandORM.created_at.desc()).limit(limit).all()
    return {"commands": [_as_dict(row) for row in rows], "physical_execution_enabled": False}


@router.get("/ponds/{pond_id}/operational-history")
async def pond_operational_history(
    pond_id: str,
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    pond_repository: IPondRepository = Depends(get_pond_repository),
    telemetry_repository: ITelemetryRepository = Depends(get_telemetry_repository),
) -> dict[str, Any]:
    verify_farm_access(user, farm_id)
    if not pond_repository.get(farm_id=farm_id, pond_id=pond_id):
        raise HTTPException(status_code=404, detail="Pond not found in the selected farm.")
    decisions = session.query(AgentDecisionORM).filter_by(farm_id=farm_id, pond_id=pond_id).order_by(
        AgentDecisionORM.updated_at.desc()).limit(limit).all()
    commands = session.query(EdgeCommandORM).filter_by(farm_id=farm_id, pond_id=pond_id).order_by(
        EdgeCommandORM.created_at.desc()).limit(limit).all()
    telemetry = telemetry_repository.get_history(farm_id=farm_id, pond_id=pond_id, limit=min(limit, 100))
    events: list[dict[str, Any]] = []
    for row in decisions:
        events.append({"kind": "DECISION", "timestamp": row.updated_at.isoformat() if row.updated_at else None,
                       "decision": {"decision_id": row.decision_id, "title": row.title, "status": row.status,
                                    "severity": row.severity, "finding_id": row.finding_id,
                                    "linked_action_id": (json.loads(row.finding_snapshot_json or "{}").get("source_action_id") if row.finding_snapshot_json else row.finding_id),
                                    "outcome_status": row.outcome_status}})
    for row in commands:
        events.append({"kind": "EDGE_COMMAND", "timestamp": row.created_at.isoformat() if row.created_at else None,
                       "command": _as_dict(row)})
    for packet in telemetry:
        events.append({"kind": "TELEMETRY", "timestamp": packet.timestamp.isoformat(),
                       "is_simulated": packet.is_simulated,
                       "metrics": {key.value if hasattr(key, "value") else str(key): value.model_dump(mode="json")
                                   for key, value in packet.metrics.items()}})
    events.sort(key=lambda event: event.get("timestamp") or "", reverse=True)
    return {"farm_id": farm_id, "pond_id": pond_id, "events": events[:limit],
            "telemetry_source_note": "Simulated records are explicitly marked; this endpoint does not infer physical equipment state."}


@router.post("/decisions/{decision_id}/verify-telemetry")
async def verify_decision_with_fresh_telemetry(
    decision_id: str,
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    max_age_seconds: int = Query(default=600, ge=1, le=86400),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    telemetry_repository: ITelemetryRepository = Depends(get_telemetry_repository),
) -> dict[str, Any]:
    """Check whether fresh telemetry exists after the decision; does not assert resolution."""
    verify_farm_access(user, farm_id)
    decision = session.query(AgentDecisionORM).filter_by(decision_id=decision_id, farm_id=farm_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found.")
    if not decision.pond_id:
        raise HTTPException(status_code=422, detail="Farm-wide decisions need a domain-specific verification workflow.")
    latest = telemetry_repository.get_latest(farm_id=farm_id, pond_id=decision.pond_id)
    now = datetime.now(timezone.utc)
    if not latest:
        return {"decision_id": decision_id, "verification_status": "INSUFFICIENT_DATA", "resolved": None,
                "reason": "No telemetry is available for this pond.", "physical_execution_enabled": False}
    packet, evaluation = latest
    timestamp = packet.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (now - timestamp).total_seconds())
    decision_time = decision.updated_at or decision.created_at
    if decision_time and decision_time.tzinfo is None:
        decision_time = decision_time.replace(tzinfo=timezone.utc)
    is_after_decision = bool(decision_time and timestamp > decision_time)
    fresh = age_seconds <= max_age_seconds and is_after_decision
    if not fresh:
        status_value = "INSUFFICIENT_FRESH_DATA"
    elif evaluation and evaluation.is_safe:
        status_value = "FRESH_DATA_CURRENTLY_SAFE"
    elif evaluation:
        status_value = "FRESH_DATA_STILL_FLAGGED"
    else:
        status_value = "FRESH_DATA_WITHOUT_EVALUATION"
    return {"decision_id": decision_id, "farm_id": farm_id, "pond_id": decision.pond_id,
            "verification_status": status_value, "resolved": None,
            "telemetry_timestamp": packet.timestamp.isoformat(), "telemetry_age_seconds": round(age_seconds, 1),
            "telemetry_is_simulated": bool(packet.is_simulated), "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
            "note": "Fresh telemetry is evidence for review, not proof of causation or physical actuator state.",
            "physical_execution_enabled": False}
