"""Chats are kept for CHAT_RETENTION_DAYS (default 365) and all of them are listed."""
from __future__ import annotations

import asyncio

from sqlalchemy.dialects import postgresql

from app.core.settings import Settings
from app.infrastructure.persistence.postgres import session_store


class FakeResult:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return []


class FakeDb:
    def __init__(self):
        self.statements = []
        self.committed = False

    async def execute(self, stmt):
        self.statements.append(str(stmt.compile(dialect=postgresql.dialect())))
        return FakeResult(rowcount=2)

    async def commit(self):
        self.committed = True


def test_default_retention_is_one_year():
    assert Settings.model_fields["chat_retention_days"].default == 365


def test_cleanup_deletes_old_turns_sessions_and_logs():
    db = FakeDb()
    counts = asyncio.run(session_store.delete_expired_sessions(db, 365))
    sql = "\n".join(db.statements)
    assert "DELETE FROM conversation_turns" in sql
    assert "DELETE FROM sessions" in sql
    assert "DELETE FROM retrieval_log " in sql
    assert "sessions.last_active <" in sql and "sessions.message_count =" in sql
    assert db.committed and counts == {"sessions": 2, "turns": 2, "retrieval_logs": 2}


def test_sidebar_list_skips_empty_sessions_in_the_query_and_allows_a_year_of_chats():
    db = FakeDb()
    asyncio.run(session_store.list_sessions(db))
    sql = db.statements[0]
    assert "sessions.message_count >" in sql            # empty sessions filtered before the limit
    import inspect
    assert inspect.signature(session_store.list_sessions).parameters["limit"].default == 500
