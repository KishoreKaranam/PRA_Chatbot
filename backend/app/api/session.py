"""
Session API Router
==================
Provides two endpoints for session lifecycle management:

  POST /session                       → create a new session, return session_id
  GET  /session/{session_id}/history  → load past conversation turns

The session_id returned by POST /session should be stored in the browser
(localStorage) and sent with every chat request.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.postgres.database import get_db
from app.infrastructure.persistence.postgres.session_store import create_session, load_history_full

router = APIRouter(prefix="/session", tags=["session"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """
    Optional payload for POST /session.
    user_id can be an email, display name, or any opaque identifier.
    Leave it null for anonymous sessions.
    """
    user_id: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str     # UUID string — store this in localStorage
    message: str = "Session created"


class HistoryTurn(BaseModel):
    """One turn returned by GET /session/{id}/history."""
    id: int
    role: str                       # "user" or "assistant"
    raw_content: str
    rewritten_content: str | None
    intent: str | None
    is_followup: bool
    entities: list[str]
    confidence: float | None
    modes_used: list[str]
    timestamp: str | None           # ISO 8601


class SessionHistoryResponse(BaseModel):
    session_id: str
    turn_count: int
    turns: list[HistoryTurn]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_new_session(
    body: CreateSessionRequest = CreateSessionRequest(),
    db: AsyncSession = Depends(get_db),
) -> CreateSessionResponse:
    """
    Create a new conversation session.

    Call this once when the user opens the app (or clicks "New Chat").
    Store the returned `session_id` in localStorage and include it in
    every subsequent chat request.

    Returns:
        201  { session_id: "uuid-string", message: "Session created" }
        500  if the database write fails
    """
    try:
        session_id = await create_session(db, user_id=body.user_id)
        return CreateSessionResponse(session_id=session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create session: {exc}") from exc


@router.get("/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> SessionHistoryResponse:
    """
    Load the conversation history for a session.

    Query params:
        limit (int, default 50)  — max number of turns to return

    Returns:
        200  { session_id, turn_count, turns: [...] }
        404  if session_id format is invalid (bad UUID)
        500  if the database read fails

    Each turn includes full metadata: role, raw vs rewritten content,
    intent, entities, confidence, modes_used.
    """
    # Validate UUID format early so we get a 404 instead of 500
    try:
        import uuid
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid session_id format")

    try:
        turns_raw: list[dict[str, Any]] = await load_history_full(db, session_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load history: {exc}") from exc

    turns = [HistoryTurn(**t) for t in turns_raw]
    return SessionHistoryResponse(
        session_id=session_id,
        turn_count=len(turns),
        turns=turns,
    )
