"""Authenticated, read-only Farm Operations Agent endpoints."""

from typing import Any
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session, get_pond_repository, get_telemetry_repository
from apps.api.src.domain.interfaces import IPondRepository, ITelemetryRepository
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from sqlalchemy.orm import Session
from apps.api.src.agent.farm_operations_agent import FarmOperationsAgent
from apps.api.src.agent.conversation_memory import ConversationMemory
from apps.api.src.infrastructure.models import AgentDecisionORM
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from packages.telemetry_schema.models import MetricType

router = APIRouter(prefix="/agent", tags=["Farm Operations Agent"])


class AgentQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    farm_id: str = Field(default=settings.default_farm_id, min_length=2, max_length=64)
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)


class AgentQueryResponse(BaseModel):
    agent: str
    agent_version: str
    mode: str
    intent: str
    answer: str
    evidence: list[dict[str, Any]]
    limitations: list[str]
    evaluated_at: str | None = None
    conversation_id: str | None = None
    decision_review: dict[str, Any] | None = None


@router.get("/capabilities")
async def get_agent_capabilities(
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
) -> dict[str, Any]:
    """Describe the currently enabled agent tools and safety boundary."""
    return {
        "agent": "farm_operations_agent",
        "version": "0.6.0",
        "mode": "READ_ONLY_TOOL_ROUTED_MVP",
        "capabilities": [
            {"name": "farm_overview", "description": "Summarize pond states from latest authorized telemetry."},
            {"name": "pond_status", "description": "Inspect latest telemetry and status for a pond."},
            {"name": "low_oxygen_risk", "description": "Find ponds with low measured DO or missing/stale evidence."},
            {"name": "telemetry_health", "description": "Find ponds with missing or stale telemetry."},
            {"name": "farm_actions", "description": "Prioritized cross-module action items."},
            {"name": "production_summary", "description": "Farm production and calculated biomass summary."},
            {"name": "feed_inventory", "description": "Recorded feed inventory and low-stock summary."},
            {"name": "water_status", "description": "Pond water-level and outlet software states."},
            {"name": "power_status", "description": "Configured transformer load estimates."},
            {"name": "working_capital", "description": "Recorded farm cash and working-capital summary."},
            {"name": "pond_health", "description": "Health summary for a specified pond."},
        ],
        "optional_features": {
            "llm_grounded_synthesis": "Enabled only when AQUA_AGENT_LLM_ENABLED=true and AQUA_AGENT_LLM_API_KEY is configured; deterministic fallback remains available.",
            "conversation_memory": "Farm- and user-scoped persistent history; contextual memory never replaces live data retrieval.",
            "cross_module_reasoning": "Fixed read-only tool orchestration for explicit cross-domain questions.",
            "decision_review": "Source-linked, deduplicated advisory findings; missing tools are explicitly reported.",
        },
        "operator_decision_tracking": "Advisory snapshot, approval/rejection, and human-reported outcome audit trail; no actuation.",
        "not_enabled": ["equipment actuation", "automatic treatment or dosing", "autonomous safety-rule changes"],
        "safety_boundary": "Read-only. Physical actuator control remains outside this agent.",
        "user_id": user.user_id,
    }


@router.post("/query", response_model=AgentQueryResponse)
async def query_farm_operations_agent(
    request: AgentQueryRequest,
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    pond_repository: IPondRepository = Depends(get_pond_repository),
    telemetry_repository: ITelemetryRepository = Depends(get_telemetry_repository),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Answer an operator question using only the authenticated farm's current data."""
    verify_farm_access(user, request.farm_id)
    memory = ConversationMemory(session)
    conversation_id = request.conversation_id
    try:
        if conversation_id:
            if not memory.owns(conversation_id=conversation_id, farm_id=request.farm_id, user_id=user.user_id):
                raise HTTPException(status_code=404, detail="Conversation not found.")
            history = memory.recent_turns(conversation_id=conversation_id, farm_id=request.farm_id, user_id=user.user_id)
        else:
            conversation_id = memory.create(farm_id=request.farm_id, user_id=user.user_id, first_question=request.question)
            history = []

        allowed_tools = {
            "farm_overview", "pond_status", "low_oxygen_risk", "telemetry_health",
            "farm_actions", "production_summary", "feed_inventory", "water_status",
            "power_status", "pond_health",
        }
        if user.has_permission(Permission.AUDIT_READ):
            allowed_tools.add("working_capital")
        agent = FarmOperationsAgent(
            pond_repository, telemetry_repository, session=session,
            allowed_tool_names=allowed_tools,
        )
        contextual_question = _resolve_contextual_followup(request.question, history)
        result = agent.answer(farm_id=request.farm_id, question=contextual_question)
        memory.append_turn(conversation_id=conversation_id, farm_id=request.farm_id, user_id=user.user_id,
                           role="user", content=request.question)
        memory.append_turn(conversation_id=conversation_id, farm_id=request.farm_id, user_id=user.user_id,
                           role="assistant", content=result.get("answer", ""), metadata={
                               "intent": result.get("intent"), "mode": result.get("mode"),
                               "evaluated_at": result.get("evaluated_at"),
                               "evidence_tools": [item.get("tool") for item in result.get("evidence", []) if isinstance(item, dict) and item.get("tool")],
                           })
        session.commit()
        result["conversation_id"] = conversation_id
        return result
    except HTTPException:
        session.rollback()
        raise
    except (ValueError, KeyError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail="Unable to evaluate this question against current farm data.") from exc
    except Exception:
        session.rollback()
        raise


def _resolve_contextual_followup(question: str, history: list[dict[str, Any]]) -> str:
    """Resolve only obvious follow-ups; never use remembered values as current evidence."""
    normalized = " ".join(question.lower().split())
    if not history:
        return question
    is_followup = any(token in normalized for token in ("that pond", "this pond", "same pond", "there", "it", "why?", "what about", "explain more", "and then"))
    if not is_followup or __import__("re").search(r"\bpond[- ]?\d{1,3}\b", normalized):
        return question
    recent_text = " ".join(turn.get("content", "") for turn in history[-4:])
    matches = __import__("re").findall(r"\bpond[- ]?0*([0-9]{1,3})\b", recent_text.lower())
    if matches:
        return f"{question} (context: pond-{int(matches[-1]):02d}; retrieve fresh current data before answering)"
    previous_user = next((turn.get("content", "") for turn in reversed(history) if turn.get("role") == "user"), "")
    if normalized in {"why?", "why", "explain more", "what about it?", "and then?"} and previous_user:
        return f"Explain the previous question in more detail: {previous_user}. Current evidence must be retrieved again."
    return question


@router.get("/conversations")
async def list_agent_conversations(
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    verify_farm_access(user, farm_id)
    return {"conversations": ConversationMemory(session).list_conversations(farm_id=farm_id, user_id=user.user_id)}


@router.get("/conversations/{conversation_id}")
async def get_agent_conversation(
    conversation_id: str,
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    verify_farm_access(user, farm_id)
    memory = ConversationMemory(session)
    if not memory.owns(conversation_id=conversation_id, farm_id=farm_id, user_id=user.user_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"conversation_id": conversation_id, "turns": memory.recent_turns(conversation_id=conversation_id, farm_id=farm_id, user_id=user.user_id, limit=12)}


@router.delete("/conversations/{conversation_id}")
async def delete_agent_conversation(
    conversation_id: str,
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    verify_farm_access(user, farm_id)
    if not ConversationMemory(session).delete(conversation_id=conversation_id, farm_id=farm_id, user_id=user.user_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    session.commit()
    return {"deleted": True, "conversation_id": conversation_id}


class DecisionCreateRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id, min_length=2, max_length=64)
    finding: dict[str, Any]
    operator_note: str | None = Field(default=None, max_length=2000)


class DecisionReviewRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id, min_length=2, max_length=64)
    decision: str = Field(..., pattern="^(APPROVE|REJECT)$")
    note: str | None = Field(default=None, max_length=2000)


class DecisionOutcomeRequest(BaseModel):
    farm_id: str = Field(default=settings.default_farm_id, min_length=2, max_length=64)
    outcome_status: str = Field(..., pattern="^(RESOLVED|NOT_RESOLVED|INCONCLUSIVE|NO_ACTION_TAKEN)$")
    outcome_note: str = Field(..., min_length=3, max_length=3000)


def _verify_outcome_against_telemetry(session: Session, farm_id: str, pond_id: str | None, finding: dict[str, Any]) -> dict[str, Any]:
    """Verify whether subsequent telemetry confirms resolution of the underlying condition."""
    if not pond_id:
        return {"verified": None, "reason": "No specific pond linked to finding"}
    telemetry_repo = SQLTelemetryRepository(session)
    record = telemetry_repo.get_latest(farm_id, pond_id)
    if not record:
        return {"verified": False, "reason": "No subsequent telemetry available for verification"}
    packet, evaluation = record
    now = datetime.now(timezone.utc)
    ts = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
    age = max(0.0, (now - ts).total_seconds())
    if age > 120.0:
        return {
            "verified": False,
            "reason": f"Telemetry is stale ({int(age)}s old); live verification pending fresh readings",
            "age_seconds": round(age, 1),
        }

    title = str(finding.get("title") or "").lower()
    do_reading = packet.metrics.get(MetricType.DISSOLVED_OXYGEN)
    do_val = do_reading.value if (do_reading and do_reading.quality.value in {"GOOD", "SUSPECT_DRIFT"}) else None
    severity = evaluation.severity.value if evaluation else "NORMAL"
    is_safe = evaluation.is_safe if evaluation else True

    if any(k in title for k in ("oxygen", "do", "hypoxia", "aerat")):
        if do_val is not None and do_val >= 4.0 and severity in {"NORMAL", "WARNING"}:
            return {
                "verified": True,
                "reason": f"Subsequent telemetry confirms DO recovered to {do_val:.2f} mg/L (Safety: {severity})",
                "verified_at": ts.isoformat(),
                "current_metric": {"dissolved_oxygen_mg_l": do_val, "severity": severity},
            }
        else:
            return {
                "verified": False,
                "reason": f"Current DO is {do_val} mg/L; recovery threshold of >= 4.0 mg/L not yet confirmed",
                "verified_at": ts.isoformat(),
                "current_metric": {"dissolved_oxygen_mg_l": do_val, "severity": severity},
            }

    if is_safe and severity in {"NORMAL", "WARNING"}:
        return {
            "verified": True,
            "reason": f"Subsequent telemetry indicates safe operational status ({severity})",
            "verified_at": ts.isoformat(),
        }
    return {
        "verified": False,
        "reason": f"Current safety state remains {severity}",
        "verified_at": ts.isoformat(),
    }


def _decision_to_dict(row: AgentDecisionORM, session: Session | None = None) -> dict[str, Any]:
    try:
        finding = json.loads(row.finding_snapshot_json)
    except (TypeError, json.JSONDecodeError):
        finding = {"title": row.title, "finding_id": row.finding_id}
    try:
        history = json.loads(row.event_history_json or "[]")
    except (TypeError, json.JSONDecodeError):
        history = []

    verification = None
    if session is not None and row.status == "COMPLETED":
        verification = _verify_outcome_against_telemetry(session, row.farm_id, row.pond_id, finding)

    return {
        "decision_id": row.decision_id, "farm_id": row.farm_id,
        "finding_id": row.finding_id, "linked_action_id": finding.get("source_action_id") or finding.get("action_id") or finding.get("finding_id") or row.finding_id,
        "correlation_key": finding.get("correlation_key"), "correlated_recommendations": finding.get("correlated_recommendations", []),
        "title": row.title, "pond_id": row.pond_id,
        "severity": row.severity, "status": row.status, "finding": finding,
        "operator_note": row.operator_note, "outcome_status": row.outcome_status,
        "outcome_note": row.outcome_note, "history": history,
        "telemetry_verification": verification,
        "created_by": row.created_by, "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "physical_actuation_performed": False,
    }


def _append_decision_event(row: AgentDecisionORM, *, actor_id: str, event: str, note: str | None = None) -> None:
    try:
        history = json.loads(row.event_history_json or "[]")
    except (TypeError, json.JSONDecodeError):
        history = []
    history.append({"event": event, "actor_id": actor_id, "note": note,
                    "timestamp": datetime.now(timezone.utc).isoformat()})
    row.event_history_json = json.dumps(history[-100:], separators=(",", ":"), ensure_ascii=False)
    row.updated_by = actor_id
    row.updated_at = datetime.now(timezone.utc)


def _decision_correlation_key(finding: dict[str, Any]) -> str:
    """Build a conservative issue key; explicit source action IDs take precedence."""
    explicit = str(finding.get("correlation_key") or "").strip().lower()
    if explicit:
        return explicit[:180]
    pond = str(finding.get("pond_id") or "farm-wide").strip().lower()
    category = str(finding.get("category") or "unknown").strip().lower()
    title = " ".join(str(finding.get("title") or "").lower().split())
    # Use the full normalized title, not category alone, to avoid merging unrelated issues.
    return f"{pond}|{category}|{title}"[:180]


@router.post("/decisions", status_code=201)
async def create_operator_decision(
    request: DecisionCreateRequest,
    user: UserIdentity = Depends(require_permission(Permission.ADVISORY_ACK)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Persist an evidence snapshot for operator review. This does not execute actions."""
    verify_farm_access(user, request.farm_id)
    finding = request.finding
    finding_id = str(finding.get("finding_id") or finding.get("action_id") or "").strip()
    title = str(finding.get("title") or "").strip()
    if not finding_id or not title:
        raise HTTPException(status_code=422, detail="finding_id and title are required in the finding snapshot.")
    snapshot = json.dumps(finding, separators=(",", ":"), ensure_ascii=False, default=str)
    if len(snapshot) > 20000:
        raise HTTPException(status_code=413, detail="Finding snapshot exceeds the allowed size.")
    correlation_key = _decision_correlation_key(finding)
    # Correlate an identical unresolved issue instead of creating a second active inbox item.
    open_rows = session.query(AgentDecisionORM).filter(
        AgentDecisionORM.farm_id == request.farm_id,
        AgentDecisionORM.status.in_(["PENDING_REVIEW", "APPROVED"]),
    ).order_by(AgentDecisionORM.updated_at.desc()).limit(200).all()
    for existing in open_rows:
        try:
            existing_finding = json.loads(existing.finding_snapshot_json or "{}")
        except json.JSONDecodeError:
            existing_finding = {}
        existing_key = existing_finding.get("correlation_key") or _decision_correlation_key(existing_finding)
        if existing_key == correlation_key:
            related = list(existing_finding.get("correlated_recommendations", []))
            related.append({"finding_id": finding_id, "title": title, "source_action_id": finding.get("source_action_id") or finding.get("action_id") or finding_id, "correlated_at": datetime.now(timezone.utc).isoformat()})
            existing_finding["correlation_key"] = correlation_key
            existing_finding["correlated_recommendations"] = related[-20:]
            existing.finding_snapshot_json = json.dumps(existing_finding, separators=(",", ":"), ensure_ascii=False, default=str)
            _append_decision_event(existing, actor_id=user.user_id, event="DUPLICATE_RECOMMENDATION_CORRELATED", note=f"Correlated finding {finding_id}")
            session.commit()
            session.refresh(existing)
            return _decision_to_dict(existing, session=session)
    finding = dict(finding)
    finding["correlation_key"] = correlation_key
    finding["source_action_id"] = finding.get("source_action_id") or finding.get("action_id") or finding_id
    snapshot = json.dumps(finding, separators=(",", ":"), ensure_ascii=False, default=str)
    decision_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    row = AgentDecisionORM(
        decision_id=decision_id, farm_id=request.farm_id, created_by=user.user_id,
        updated_by=user.user_id, finding_id=finding_id, title=title[:240],
        pond_id=str(finding.get("pond_id"))[:64] if finding.get("pond_id") else None,
        severity=str(finding.get("severity") or "UNKNOWN")[:32].upper(),
        status="PENDING_REVIEW", finding_snapshot_json=snapshot,
        operator_note=request.operator_note, outcome_note=None, outcome_status=None,
        event_history_json="[]", created_at=now, updated_at=now,
    )
    _append_decision_event(row, actor_id=user.user_id, event="CREATED_FOR_REVIEW", note=request.operator_note)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _decision_to_dict(row, session=session)


@router.get("/decisions")
async def list_operator_decisions(
    farm_id: str = Query(default=settings.default_farm_id, min_length=2, max_length=64),
    status: str | None = Query(default=None, pattern="^(PENDING_REVIEW|APPROVED|REJECTED|COMPLETED|CANCELLED)$"),
    limit: int = Query(default=50, ge=1, le=100),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    verify_farm_access(user, farm_id)
    query = session.query(AgentDecisionORM).filter(AgentDecisionORM.farm_id == farm_id)
    if status:
        query = query.filter(AgentDecisionORM.status == status)
    rows = query.order_by(AgentDecisionORM.updated_at.desc()).limit(limit).all()
    return {"decisions": [_decision_to_dict(row, session=session) for row in rows]}


@router.post("/decisions/{decision_id}/review")
async def review_operator_decision(
    decision_id: str,
    request: DecisionReviewRequest,
    user: UserIdentity = Depends(require_permission(Permission.ADVISORY_ACK)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Approve/reject an advisory only; approval is not permission to actuate hardware."""
    verify_farm_access(user, request.farm_id)
    row = session.query(AgentDecisionORM).filter_by(decision_id=decision_id, farm_id=request.farm_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Decision not found.")
    if row.status != "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail=f"Decision cannot be reviewed from status {row.status}.")
    row.status = "APPROVED" if request.decision == "APPROVE" else "REJECTED"
    row.operator_note = request.note or row.operator_note
    _append_decision_event(row, actor_id=user.user_id, event=row.status, note=request.note)
    session.commit()
    session.refresh(row)
    return _decision_to_dict(row, session=session)


@router.post("/decisions/{decision_id}/outcome")
async def record_operator_outcome(
    decision_id: str,
    request: DecisionOutcomeRequest,
    user: UserIdentity = Depends(require_permission(Permission.ADVISORY_ACK)),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Record a human-reported outcome; verify against subsequent telemetry."""
    verify_farm_access(user, request.farm_id)
    row = session.query(AgentDecisionORM).filter_by(decision_id=decision_id, farm_id=request.farm_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Decision not found.")
    if row.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Only an approved decision can receive an outcome.")
    row.status = "COMPLETED"
    row.outcome_status = request.outcome_status
    row.outcome_note = request.outcome_note.strip()
    _append_decision_event(row, actor_id=user.user_id, event="OUTCOME_RECORDED",
                           note=f"{request.outcome_status}: {request.outcome_note.strip()}")
    try:
        finding = json.loads(row.finding_snapshot_json or "{}")
    except json.JSONDecodeError:
        finding = {}
    verification = _verify_outcome_against_telemetry(session, row.farm_id, row.pond_id, finding)
    if verification.get("verified") is True:
        _append_decision_event(row, actor_id="telemetry_verifier", event="TELEMETRY_VERIFIED", note=verification.get("reason"))
    elif verification.get("verified") is False:
        _append_decision_event(row, actor_id="telemetry_verifier", event="TELEMETRY_UNVERIFIED", note=verification.get("reason"))
    session.commit()
    session.refresh(row)
    return _decision_to_dict(row, session=session)
