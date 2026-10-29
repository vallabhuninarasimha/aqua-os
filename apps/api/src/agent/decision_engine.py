"""Evidence-linked farm decision review; advisory only, never actuates equipment."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_SEVERITY_RANK = {"EMERGENCY": 0, "CRITICAL": 1, "HIGH": 1, "WARNING": 2, "MEDIUM": 2, "INFO": 3, "LOW": 4}


def build_decision_review(evidence: list[dict[str, Any]], *, evaluated_at: str | None = None) -> dict[str, Any]:
    """Summarize source-backed action items without manufacturing farm facts.

    Only explicit action records returned by authorized domain tools become findings.
    A failed/missing tool is represented as unavailable, never as a healthy domain.
    """
    evaluated_at = evaluated_at or datetime.now(timezone.utc).isoformat()
    findings: dict[str, dict[str, Any]] = {}
    unavailable: list[str] = []
    successful_tools: list[str] = []

    for item in evidence:
        tool = str(item.get("tool", "unknown"))
        if item.get("error") or item.get("data_class") == "UNAVAILABLE":
            unavailable.append(tool)
            continue
        successful_tools.append(tool)
        if tool != "farm_actions":
            continue
        result = item.get("result")
        action_items = _extract_action_items(result)
        for raw_action in action_items:
            if hasattr(raw_action, "model_dump"):
                action = raw_action.model_dump(mode="json")
            elif hasattr(raw_action, "dict") and callable(raw_action.dict):
                action = raw_action.dict()
            elif isinstance(raw_action, dict):
                action = raw_action
            else:
                action = vars(raw_action)
            action_id = str(action.get("action_id") or action.get("id") or "").strip()
            title = str(action.get("title") or action.get("name") or "").strip()
            if not action_id and not title:
                continue
            key = action_id or title.lower()
            severity = str(action.get("severity") or "UNKNOWN").upper()
            finding = {
                "finding_id": action_id or key,
                "title": title or "Action requires review",
                "severity": severity,
                "priority_rank": _SEVERITY_RANK.get(severity, 5),
                "pond_id": action.get("pond_id"),
                "scope": action.get("scope", "UNKNOWN"),
                "category": action.get("category", "UNKNOWN"),
                "reason": action.get("reason"),
                "evidence": action.get("supporting_evidence") or action.get("evidence") or {},
                "confidence": action.get("confidence", "UNSPECIFIED"),
                "source_timestamp": action.get("source_data_timestamp"),
                "recommended_next_step": action.get("recommended_next_step"),
                "is_advisory": bool(action.get("is_advisory", True)),
                "physical_state_confirmed": bool(action.get("physical_state_confirmed", False)),
                "source_tool": tool,
                "requires_operator_review": True,
            }
            prior = findings.get(key)
            if prior is None or finding["priority_rank"] < prior["priority_rank"]:
                findings[key] = finding

    ordered = sorted(findings.values(), key=lambda f: (f["priority_rank"], str(f.get("pond_id") or ""), f["finding_id"]))
    counts: dict[str, int] = {}
    for finding in ordered:
        severity = finding["severity"]
        counts[severity] = counts.get(severity, 0) + 1

    if unavailable:
        status = "PARTIAL"
    elif successful_tools:
        status = "AVAILABLE"
    else:
        status = "UNAVAILABLE"

    return {
        "status": status,
        "evaluated_at": evaluated_at,
        "finding_count": len(ordered),
        "severity_counts": counts,
        "findings": ordered,
        "source_tools_succeeded": sorted(set(successful_tools)),
        "source_tools_unavailable": sorted(set(unavailable)),
        "decision_policy": "SOURCE_BACKED_ADVISORY_ONLY",
        "limitations": [
            "Findings are derived only from records returned by authorized domain tools.",
            "No missing value or unavailable subsystem is interpreted as healthy.",
            "Recommendations require operator review and verification against current farm conditions.",
            "No pump, aerator, feeder, valve, or dosing command was issued.",
            "Software state and calculated estimates do not confirm physical equipment state.",
        ],
    }


def _extract_action_items(value: Any) -> list[dict[str, Any]]:
    """Handle Pydantic responses and serialized response envelopes defensively."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "dict") and callable(value.dict):
        value = value.dict()
    if isinstance(value, dict):
        for key in ("actions", "items", "findings"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict) or hasattr(item, "__dict__")]
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict) or hasattr(item, "__dict__")]
    return []
