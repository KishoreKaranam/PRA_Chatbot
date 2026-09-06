"""
SQLAlchemy ORM Models for PRA Chatbot
======================================
Defines 4 tables:
  1. sessions           — one row per user session
  2. conversation_turns — every user question + assistant answer
  3. retrieval_log      — audit trail of every retrieval operation
  4. pra_entities_cache — PRA ontology labels loaded from TTL (for entity matching)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from app.infrastructure.persistence.postgres.database import Base


# ── Table 1: sessions ─────────────────────────────────────────────────────────

class Session(Base):
    """
    One row per user session.
    session_id is created when user first opens the app
    and stored in browser localStorage.
    """
    __tablename__ = "sessions"

    session_id    = Column(
                        UUID(as_uuid=True),
                        primary_key=True,
                        default=uuid.uuid4,
                        nullable=False,
                    )
    user_id       = Column(String(100), nullable=True)       # optional — email or name
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active   = Column(
                        DateTime,
                        default=datetime.utcnow,
                        onupdate=datetime.utcnow,
                        nullable=False,
                    )
    message_count = Column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<Session id={self.session_id} user={self.user_id} msgs={self.message_count}>"


# ── Table 2: conversation_turns ───────────────────────────────────────────────

class ConversationTurn(Base):
    """
    Every user question and assistant answer stored as separate rows.
    role = 'user' or 'assistant'

    raw_content      = original question as typed by user
    rewritten_content = after Stage 1 context resolution
                        e.g. "What rules apply to it?"
                          →  "What rules apply to ISO 20022?"
    """
    __tablename__ = "conversation_turns"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    session_id         = Column(
                             UUID(as_uuid=True),
                             ForeignKey("sessions.session_id", ondelete="CASCADE"),
                             nullable=False,
                             index=True,        # fast lookup by session
                         )
    role               = Column(String(20),  nullable=False)   # user / assistant
    raw_content        = Column(Text,        nullable=False)   # original input
    rewritten_content  = Column(Text,        nullable=True)    # after pronoun resolution
    intent             = Column(String(50),  nullable=True)    # definition/list/comparison/exploratory/vague
    is_followup        = Column(Boolean,     default=False, nullable=False)
    entities           = Column(ARRAY(Text), nullable=True)    # PRA entities mentioned e.g. ["ISO 20022", "SCT"]
    confidence         = Column(Float,       nullable=True)    # 0.0 – 1.0 evidence confidence
    modes_used         = Column(ARRAY(Text), nullable=True)    # e.g. ["sparql", "fts", "similarity"]
    timestamp          = Column(DateTime,    default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<Turn id={self.id} session={self.session_id} role={self.role} intent={self.intent}>"


# ── Table 3: retrieval_log ────────────────────────────────────────────────────

class RetrievalLog(Base):
    """
    Audit trail — one row per retrieval operation.
    Tracks how many evidence items each mode returned
    and whether validation passed.

    Useful for:
      - Analytics (which modes are most used?)
      - Debugging (why did this question get no evidence?)
      - Monitoring (confidence trends over time)
    """
    __tablename__ = "retrieval_log"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    session_id       = Column(UUID(as_uuid=True), nullable=False, index=True)
    question         = Column(Text,    nullable=False)
    sparql_count     = Column(Integer, default=0, nullable=False)   # triples from SPARQL
    neo4j_count      = Column(Integer, default=0, nullable=False)   # evidence items from Neo4j
    fts_count        = Column(Integer, default=0, nullable=False)   # hits from FTS
    similarity_count = Column(Integer, default=0, nullable=False)   # hits from similarity
    evidence_passed  = Column(Boolean, default=False, nullable=False)  # did Stage 5 validation pass?
    confidence       = Column(Float,   nullable=True)               # final confidence score
    timestamp        = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<RetrievalLog id={self.id} sparql={self.sparql_count} "
            f"neo4j={self.neo4j_count} fts={self.fts_count} "
            f"sim={self.similarity_count} passed={self.evidence_passed}>"
        )


# ── Table 4: pra_entities_cache ───────────────────────────────────────────────

class PRAEntityCache(Base):
    """
    All entity labels loaded from pra_ontology.ttl at startup.
    Used by Stage 1 Layer B entity matching to resolve pronouns.

    Example rows:
      entity_id  = "https://example.org/pra#func_FraudCheck"
      label      = "Fraud Check"
      entity_type= "BusinessFunction"
      normalized = "fraud check"
      aliases    = ["Fraud Detection", "Anti-Fraud"]

    Refreshed every time the backend starts (sync_entity_cache).
    """
    __tablename__ = "pra_entities_cache"

    entity_id        = Column(String(500), primary_key=True, nullable=False)  # full URI
    label            = Column(Text,        nullable=False)                     # rdfs:label
    entity_type      = Column(String(100), nullable=True)                     # BusinessFunction / Domain / etc.
    normalized_label = Column(Text,        nullable=True)                     # lowercase for matching
    aliases          = Column(ARRAY(Text), nullable=True)                     # skos:altLabel values

    def __repr__(self) -> str:
        return f"<PRAEntity label='{self.label}' type={self.entity_type}>"
