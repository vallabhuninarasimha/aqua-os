"""Persistent, tenant-scoped conversation history for Farm Operations Agent.

Conversation history is contextual only. It is not a source of live farm truth;
operational answers must retrieve current evidence from authorized domain tools.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import AgentConversationORM, AgentConversationTurnORM

MAX_TURNS = 40
MAX_CONTENT_CHARS = 6000


class ConversationMemory:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, farm_id: str, user_id: str, first_question: str) -> str:
        conversation_id = str(uuid.uuid4())
        title = re.sub(r"\s+", " ", first_question).strip()[:157] or "Farm operations conversation"
        if len(first_question) > 157:
            title += "..."
        now = datetime.now(timezone.utc)
        self._session.add(AgentConversationORM(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id,
            title=title, created_at=now, updated_at=now,
        ))
        self._session.flush()
        return conversation_id

    def owns(self, *, conversation_id: str, farm_id: str, user_id: str) -> bool:
        return self._session.query(AgentConversationORM.conversation_id).filter_by(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id
        ).first() is not None

    def append_turn(
        self, *, conversation_id: str, farm_id: str, user_id: str,
        role: str, content: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Invalid conversation role")
        safe_content = str(content)[:MAX_CONTENT_CHARS]
        now = datetime.now(timezone.utc)
        self._session.add(AgentConversationTurnORM(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id,
            role=role, content=safe_content,
            metadata_json=json.dumps(metadata or {}, separators=(",", ":"), default=str)[:12000],
            created_at=now,
        ))
        conversation = self._session.query(AgentConversationORM).filter_by(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id
        ).first()
        if conversation:
            conversation.updated_at = now
        self._session.flush()
        # Bound storage per conversation to the latest 40 turns without deleting other users' data.
        old_ids = self._session.query(AgentConversationTurnORM.id).filter_by(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id
        ).order_by(desc(AgentConversationTurnORM.id)).offset(MAX_TURNS).all()
        if old_ids:
            self._session.query(AgentConversationTurnORM).filter(
                AgentConversationTurnORM.id.in_([row[0] for row in old_ids]),
                AgentConversationTurnORM.conversation_id == conversation_id,
                AgentConversationTurnORM.farm_id == farm_id,
                AgentConversationTurnORM.user_id == user_id,
            ).delete(synchronize_session=False)

    def recent_turns(self, *, conversation_id: str, farm_id: str, user_id: str, limit: int = 8) -> list[dict[str, Any]]:
        rows = self._session.query(AgentConversationTurnORM).filter_by(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id
        ).order_by(desc(AgentConversationTurnORM.id)).limit(max(1, min(limit, 12))).all()
        return [{"role": row.role, "content": row.content, "created_at": row.created_at.isoformat()} for row in reversed(rows)]

    def list_conversations(self, *, farm_id: str, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._session.query(AgentConversationORM).filter_by(
            farm_id=farm_id, user_id=user_id
        ).order_by(desc(AgentConversationORM.updated_at)).limit(max(1, min(limit, 50))).all()
        return [{"conversation_id": row.conversation_id, "title": row.title,
                 "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}
                for row in rows]

    def delete(self, *, conversation_id: str, farm_id: str, user_id: str) -> bool:
        conversation = self._session.query(AgentConversationORM).filter_by(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id
        ).first()
        if not conversation:
            return False
        self._session.query(AgentConversationTurnORM).filter_by(
            conversation_id=conversation_id, farm_id=farm_id, user_id=user_id
        ).delete(synchronize_session=False)
        self._session.delete(conversation)
        return True
