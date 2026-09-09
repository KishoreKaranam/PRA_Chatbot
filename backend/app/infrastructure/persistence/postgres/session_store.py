"""
Session Store
=============
All database operations for sessions, conversation turns, and retrieval logs.

Functions:
  create_session(db, user_id)            → session_id (UUID str)
  load_history(db, session_id, limit)    → list[dict]  (last N turns)
  save_turn(db, session_id, role, ...)   → ConversationTurn row
  save_retrieval_log(db, session_id, ...) → RetrievalLog row
  increment_message_count(db, session_id) → None
  touch_session(db, session_id)          → None  (update last_active)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.postgres.models import ConversationTurn, RetrievalLog, Session


# ── Session operations ─────────────────────────────────────────────────────────

async def create_session(db: AsyncSession, user_id: str | None = None) -> str:
    """
    Create a new session row and return the session_id as a plain string.

    Called by:  POST /session
    Returns:    str  (UUID hex, e.g. "550e8400-e29b-41d4-a716-446655440000")
    """
    session = Session(
        session_id=uuid.uuid4(),
        user_id=user_id,
        created_at=datetime.utcnow(),
        last_active=datetime.utcnow(),
        message_count=0,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return str(session.session_id)


async def touch_session(db: AsyncSession, session_id: str) -> None:
    """
    Update last_active to now.
    Called on every user message so idle detection works correctly.
    """
    await db.execute(
        update(Session)
        .where(Session.session_id == uuid.UUID(session_id))
        .values(last_active=datetime.utcnow())
    )
    await db.commit()


async def increment_message_count(db: AsyncSession, session_id: str) -> None:
    """
    Atomically increment message_count by 1 on a session row.
    Called every time a user turn is saved.
    """
    # Load the row, increment, commit — simple and safe for our scale
    result = await db.execute(
        select(Session).where(Session.session_id == uuid.UUID(session_id))
    )
    session = result.scalar_one_or_none()
    if session:
        session.message_count = (session.message_count or 0) + 1
        session.last_active = datetime.utcnow()
        await db.commit()


async def list_sessions(
    db: AsyncSession,
    user_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Return all sessions (most-recently-active first), each annotated with
    a `title` derived from the first user question in that session.

    Used by:  GET /session  (chat-history sidebar, like ChatGPT/Claude)
    """
    query = select(Session).order_by(Session.last_active.desc()).limit(limit)
    if user_id is not None:
        query = query.where(Session.user_id == user_id)

    result = await db.execute(query)
    sessions = result.scalars().all()

    output: list[dict[str, Any]] = []
    for s in sessions:
        # Skip empty sessions (created but never used) — keeps the sidebar clean
        if not s.message_count:
            continue

        first_turn_result = await db.execute(
            select(ConversationTurn)
            .where(ConversationTurn.session_id == s.session_id, ConversationTurn.role == "user")
            .order_by(ConversationTurn.timestamp.asc())
            .limit(1)
        )
        first_turn = first_turn_result.scalar_one_or_none()
        title = (first_turn.raw_content if first_turn else "New conversation").strip()
        if len(title) > 60:
            title = title[:57].rstrip() + "..."

        output.append({
            "session_id": str(s.session_id),
            "title": title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "last_active": s.last_active.isoformat() if s.last_active else None,
            "message_count": s.message_count,
        })
    return output


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    """
    Delete a session and all its conversation turns / retrieval logs
    (cascade is configured at the FK level — see models.py).

    Used by:  DELETE /session/{session_id}
    Returns:  True if a row was deleted, False if session_id didn't exist.
    """
    result = await db.execute(
        select(Session).where(Session.session_id == uuid.UUID(session_id))
    )
    session = result.scalar_one_or_none()
    if session is None:
        return False
    await db.delete(session)
    await db.commit()
    return True


# ── Conversation turn operations ───────────────────────────────────────────────

async def save_turn(
    db: AsyncSession,
    session_id: str,
    role: str,                          # "user" or "assistant"
    raw_content: str,
    *,
    rewritten_content: str | None = None,
    intent: str | None = None,
    is_followup: bool = False,
    entities: list[str] | None = None,
    confidence: float | None = None,
    modes_used: list[str] | None = None,
) -> ConversationTurn:
    """
    Persist a single conversation turn (user question or assistant answer).

    All metadata fields are optional — pass only what is available at the
    time of the call (e.g. assistant turns won't have intent/entities).

    Example — saving a user turn:
        turn = await save_turn(
            db, session_id, "user", question,
            rewritten_content=rewritten,
            intent="definition",
            is_followup=True,
            entities=["ISO 20022"],
        )

    Example — saving an assistant turn:
        turn = await save_turn(
            db, session_id, "assistant", answer,
            confidence=0.87,
            modes_used=["sparql", "fts"],
        )
    """
    turn = ConversationTurn(
        session_id=uuid.UUID(session_id),
        role=role,
        raw_content=raw_content,
        rewritten_content=rewritten_content,
        intent=intent,
        is_followup=is_followup,
        entities=entities or [],
        confidence=confidence,
        modes_used=modes_used or [],
        timestamp=datetime.utcnow(),
    )
    db.add(turn)

    # Keep message_count in sync (only count user turns)
    if role == "user":
        await increment_message_count(db, session_id)
    else:
        await db.commit()

    await db.refresh(turn)
    return turn


async def load_history(
    db: AsyncSession,
    session_id: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """
    Return the last `limit` turns for a session, ordered oldest-first.

    The sliding window matches Stage 7 of the pipeline (max 6 turns = 3 pairs).
    Returns plain dicts so callers don't need ORM knowledge:
      [
        {"role": "user",      "content": "What is ISO 20022?"},
        {"role": "assistant", "content": "ISO 20022 is a global standard ..."},
        ...
      ]

    Used by:
      - chat.py  → injects history into pipeline_service
      - GET /session/{id}/history  → returns to frontend
    """
    result = await db.execute(
        select(ConversationTurn)
        .where(ConversationTurn.session_id == uuid.UUID(session_id))
        .order_by(ConversationTurn.timestamp.desc())   # newest first
        .limit(limit)
    )
    rows = result.scalars().all()

    # Reverse so the list is oldest → newest (chronological order)
    return [
        {
            "role": row.role,
            "content": row.rewritten_content or row.raw_content,
            "intent": row.intent,
            "is_followup": row.is_followup,
            "entities": row.entities or [],
            "confidence": row.confidence,
            "modes_used": row.modes_used or [],
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        }
        for row in reversed(rows)
    ]


async def load_history_full(
    db: AsyncSession,
    session_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Richer version for the GET /session/{id}/history endpoint.
    Returns full metadata including raw_content, entities, timestamps.
    """
    result = await db.execute(
        select(ConversationTurn)
        .where(ConversationTurn.session_id == uuid.UUID(session_id))
        .order_by(ConversationTurn.timestamp.asc())
        .limit(limit)
    )
    rows = result.scalars().all()

    return [
        {
            "id": row.id,
            "role": row.role,
            "raw_content": row.raw_content,
            "rewritten_content": row.rewritten_content,
            "intent": row.intent,
            "is_followup": row.is_followup,
            "entities": row.entities or [],
            "confidence": row.confidence,
            "modes_used": row.modes_used or [],
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        }
        for row in rows
    ]


# ── Retrieval log operations ───────────────────────────────────────────────────

async def save_retrieval_log(
    db: AsyncSession,
    session_id: str,
    question: str,
    *,
    sparql_count: int = 0,
    neo4j_count: int = 0,
    fts_count: int = 0,
    similarity_count: int = 0,
    evidence_passed: bool = False,
    confidence: float | None = None,
) -> RetrievalLog:
    """
    Save a retrieval audit record after Stages 3–5 of the pipeline.

    Called from chat.py after retrieval completes so we always have a
    log entry even if the LLM call later fails.

    Example:
        await save_retrieval_log(
            db, session_id, question,
            sparql_count=len(sparql_results),
            fts_count=len(fts_results),
            similarity_count=len(sim_results),
            evidence_passed=validation_result.has_sufficient,
            confidence=validation_result.confidence,
        )
    """
    log = RetrievalLog(
        session_id=uuid.UUID(session_id),
            question=question,
            sparql_count=sparql_count,
            neo4j_count=neo4j_count,
            fts_count=fts_count,
        similarity_count=similarity_count,
        evidence_passed=evidence_passed,
        confidence=confidence,
        timestamp=datetime.utcnow(),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log
