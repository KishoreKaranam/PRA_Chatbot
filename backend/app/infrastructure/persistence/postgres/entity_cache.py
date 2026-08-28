"""
PRA Entity Cache
================
Reads all labelled entities from Neo4j and upserts them into
the `pra_entities_cache` table so Stage 1 Layer B can do fast entity
matching without touching the graph at query time.

Node labels extracted (matching new Neo4j dump schema):
  Function        → business functions inside a domain
  Domain          → main journey domains
  SupportingDomain→ supporting domains
  Rule            → business rules per function
  PaymentScheme   → payment schemes
  Phase           → journey phases
  Purpose         → function purposes
  PreCondition    → function pre-conditions
  PostCondition   → function post-conditions
  Input           → function inputs
  Output          → function outputs
  PRA             → top-level PRA node

Usage:
  await sync_entity_cache(db)   → called at startup in main.py lifespan hook
  await find_entities(db, text) → Stage 1 Layer B entity lookup
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.log_config import get_logger
from app.infrastructure.persistence.postgres.models import PRAEntityCache

logger = get_logger(__name__)

# Map Neo4j node label → friendly entity_type name stored in entity_type column
ENTITY_TYPE_MAP: dict[str, str] = {
    "Function":       "Function",
    "Domain":         "Domain",
    "SupportingDomain": "SupportingDomain",
    "Rule":           "Rule",
    "PaymentScheme":  "PaymentScheme",
    "Phase":          "Phase",
    "Purpose":        "Purpose",
    "PreCondition":   "PreCondition",
    "PostCondition":  "PostCondition",
    "Input":          "Input",
    "Output":         "Output",
    "PRA":            "PRA",
}


# ── Normalisation helpers ──────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    Lowercase, strip punctuation and extra whitespace.
    'ISO 20022 Compliant'  →  'iso 20022 compliant'
    'Fraud, Detection.'    →  'fraud detection'
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Neo4j entity extraction ────────────────────────────────────────────────────

async def _fetch_entities_from_neo4j() -> list[dict[str, Any]]:
    """
    Query Neo4j for all labelled entities and return a flat list of entity dicts.

    Each dict contains:
      entity_id        = "<Label>:<name>" — unique identifier
      label            = node.name property
      entity_type      = friendly type name (from ENTITY_TYPE_MAP)
      normalized_label = lowercased/cleaned label
      aliases          = [] (Neo4j dump has no altLabel equivalent; extend if needed)
    """
    from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient

    client = Neo4jClient()
    await client.connect()

    cypher = """
    MATCH (n)
    WHERE any(lbl IN labels(n) WHERE lbl IN $labels)
      AND n.name IS NOT NULL
    RETURN labels(n)[0] AS label_type, n.name AS name,
           coalesce(n.description, '') AS description
    """
    labels_list = list(ENTITY_TYPE_MAP.keys())

    try:
        records = await client.execute_read_query(cypher, labels=labels_list)
    finally:
        await client.close()

    result: list[dict[str, Any]] = []
    skipped = 0

    for rec in records:
        label_type = rec.get("label_type")
        name = rec.get("name") or ""

        if not label_type or not name or label_type not in ENTITY_TYPE_MAP:
            skipped += 1
            continue

        entity_type = ENTITY_TYPE_MAP[label_type]
        entity_id = f"{label_type}:{name}"

        result.append({
            "entity_id":        entity_id,
            "label":            name,
            "entity_type":      entity_type,
            "normalized_label": _normalize(name),
            "aliases":          [],
        })

    logger.info(
        "entity_cache_extracted",
        total=len(result),
        skipped=skipped,
        by_type={
            t: sum(1 for r in result if r["entity_type"] == t)
            for t in set(r["entity_type"] for r in result)
        },
    )
    return result


# ── Database sync ──────────────────────────────────────────────────────────────

async def sync_entity_cache(db: AsyncSession) -> int:
    """
    Full refresh: delete all rows then bulk-insert from Neo4j.

    Called once at startup from main.py lifespan.
    Returns the number of rows inserted.

    Strategy: full delete + re-insert (not incremental) because:
    - Graph only changes when Neo4j data is updated (rare)
    - Simpler than diffing — ensures cache is always 100 % in sync
    """
    # Step 1 — fetch entities from Neo4j
    entities = await _fetch_entities_from_neo4j()

    if not entities:
        logger.warning("entity_cache_no_entities_extracted")
        return 0

    # Step 2 — clear old cache
    await db.execute(delete(PRAEntityCache))
    await db.commit()
    logger.info("entity_cache_cleared")

    # Step 3 — bulk upsert in batches of 500
    batch_size = 500
    inserted = 0
    for i in range(0, len(entities), batch_size):
        batch = entities[i : i + batch_size]
        stmt = pg_insert(PRAEntityCache).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["entity_id"],
            set_={
                "label":            stmt.excluded.label,
                "entity_type":      stmt.excluded.entity_type,
                "normalized_label": stmt.excluded.normalized_label,
                "aliases":          stmt.excluded.aliases,
            },
        )
        await db.execute(stmt)
        inserted += len(batch)

    await db.commit()
    logger.info("entity_cache_synced", rows=inserted)
    return inserted


# ── Stage 1 Layer B: entity lookup ────────────────────────────────────────────

async def find_entities(
    db: AsyncSession,
    text: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Find PRA entities mentioned in `text` using normalized substring matching.

    Layer B of Stage 1 context resolution:
      1. Normalize the input text
      2. Check every entity's normalized_label against the text
      3. Also check each alias
      4. Return the top-k matches ordered by label length (longest = most specific)

    Example:
      text = "What rules apply to it for SEPA SCT?"
      returns → [{"label": "SEPA Credit Transfer", "entity_type": "PaymentScheme", ...}]

    For pronoun resolution ("it", "that function"):
      - Caller (Stage 1) uses this to build the injection:
        "User said 'it' which refers to SEPA Credit Transfer"

    Args:
        db:     async DB session
        text:   raw or rewritten user question
        top_k:  max entities to return

    Returns:
        list of dicts with keys: entity_id, label, entity_type, normalized_label, aliases
    """
    normalized_text = _normalize(text)
    if not normalized_text:
        return []

    # Pull all entities from cache (fits in memory — ~2000 rows max)
    result = await db.execute(select(PRAEntityCache))
    all_entities = result.scalars().all()

    matches: list[tuple[int, dict[str, Any]]] = []  # (label_length, entity_dict)

    for entity in all_entities:
        norm = entity.normalized_label or ""
        # Direct label match
        if norm and norm in normalized_text:
            matches.append((
                len(norm),
                {
                    "entity_id":   entity.entity_id,
                    "label":       entity.label,
                    "entity_type": entity.entity_type,
                    "normalized_label": norm,
                    "aliases":     entity.aliases or [],
                },
            ))
            continue

        # Alias match — any alias substring present in text?
        for alias in (entity.aliases or []):
            norm_alias = _normalize(alias)
            if norm_alias and norm_alias in normalized_text:
                matches.append((
                    len(norm_alias),
                    {
                        "entity_id":   entity.entity_id,
                        "label":       entity.label,       # use canonical label
                        "entity_type": entity.entity_type,
                        "normalized_label": norm,
                        "aliases":     entity.aliases or [],
                        "matched_alias": alias,
                    },
                ))
                break  # one alias match per entity is enough

    # Sort: longest match first (most specific entity wins)
    matches.sort(key=lambda x: x[0], reverse=True)

    return [m[1] for m in matches[:top_k]]


# ── Convenience: get entity count (for health check / startup log) ─────────────

async def get_entity_count(db: AsyncSession) -> int:
    """Return the number of rows in pra_entities_cache."""
    from sqlalchemy import func
    result = await db.execute(select(func.count()).select_from(PRAEntityCache))
    return result.scalar_one() or 0
