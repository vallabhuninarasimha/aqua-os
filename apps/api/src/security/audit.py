"""Audit logging service for security and compliance."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import AuditLogORM

# Sensitive keys filtered from audit details
REDACTED_KEYS = {"password", "token", "access_token", "secret", "authorization"}


def sanitize_details(details: Optional[Dict[str, Any]]) -> Optional[str]:
    """Sanitize dictionary to prevent logging sensitive secrets or passwords."""
    if not details:
        return None
    cleaned = {}
    for k, v in details.items():
        if k.lower() in REDACTED_KEYS:
            cleaned[k] = "[REDACTED]"
        else:
            cleaned[k] = v
    return json.dumps(cleaned)


def log_security_event(
    session: Session,
    farm_id: str,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> AuditLogORM:
    """Record an immutable security audit event."""
    audit_entry = AuditLogORM(
        timestamp=datetime.now(timezone.utc),
        farm_id=farm_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details_json=sanitize_details(details),
        ip_address=ip_address,
    )
    session.add(audit_entry)
    session.commit()
    return audit_entry

