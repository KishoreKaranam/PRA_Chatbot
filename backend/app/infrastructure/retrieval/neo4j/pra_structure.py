"""PRA structure lookups for overview and named-domain questions.

Two kinds of graph evidence that the fixed question patterns (functions,
rules, dependencies, ...) do not cover:

* PRA map      - "architecture / overview / all domains" questions: the journey
                 stages in order with their functions, the supporting layers
                 with their supporting domains, and which journey stages each
                 supporting domain serves.
* Domain profile - any question that names a domain or supporting domain, e.g.
                 "What does Foreign Exchange Management do and which journey
                 stages does it support?": description, purpose, rules,
                 functions, and its links to journey functions / other
                 supporting domains.

How the graph is organised (checked in Neo4j):
  (:PRA)-[:COMPRISES]->(:Domain)
  (:Domain)-[:CONTAINS]->(:Function)            Domain = payment journey stage
  (:Domain)-[:CONTAINS]->(:SupportingDomain)    Domain = supporting layer
  An arrow starts at the one doing the action:
  (a)-[:DEPENDS_ON_SUPPORTING]->(b)   a depends on b
  (a)-[:PROVIDES_TO_SUPPORTING]->(b)  a provides to b

The result is returned as a short, readable summary (Neo4jGraphEvidence.summary)
plus the nodes involved (used for counting and source-document links).
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from app.core.log_config import get_logger
from app.models.schemas import Neo4jGraphEvidence, Neo4jNode

logger = get_logger(__name__)

# The payment journey runs in this order (PRA Functional descriptions for
# Payments Journey). Stages not listed here are shown after these.
JOURNEY_ORDER = ["Payment Initiation", "Order Management", "Payment Processing", "Clearing", "Settlement"]

MAX_PROFILES = 8          # named domains looked up per question
MAX_LIST = 25             # items listed per line in a profile
MAX_TEXT = 300            # characters of a description / rule / purpose

_OVERVIEW_PATTERNS = [
    r"\barchitecture\b", r"\boverview\b", r"\bstructure\b", r"\bdiagram\b",
    r"\bbig picture\b", r"\bend[- ]to[- ]end\b", r"\blandscape\b",
    r"\ball (?:the )?(?:payment )?(?:journey |supporting )?(?:domains|stages|layers)\b",
    r"\blist (?:all |the )?(?:payment )?(?:journey |supporting )?(?:domains|stages|layers)\b",
    r"\b(?:what|which) (?:are the )?(?:journey |supporting )?domains\b",
]

# Words people use for a domain that differ from its name in the graph.
_ALIASES = {r"\bfx\b": "foreign exchange", r"\baml\b": "anti money laundering"}


def is_overview_question(question: str) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in _OVERVIEW_PATTERNS)


def match_key(text: str) -> str:
    """Lower-case words only; '&' and 'and' ignored (so 'Treasury & Cash' == 'Treasury and Cash')."""
    words = re.sub(r"[^a-z0-9]+", " ", text.lower().replace("&", " and ")).split()
    return " ".join(w for w in words if w != "and")


def question_key(question: str) -> str:
    q = question.lower()
    for pattern, replacement in _ALIASES.items():
        q = re.sub(pattern, replacement, q)
    return f" {match_key(q)} "


def name_keys(name: str) -> list[str]:
    """Ways a domain name can appear in a question: full name, and without '(…)'."""
    keys = {match_key(name)}
    without_brackets = re.sub(r"\([^)]*\)", " ", name)
    if without_brackets.strip() != name.strip():
        keys.add(match_key(without_brackets))
    return [k for k in keys if k]


def find_named_domains(question: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All domain / supporting-domain names mentioned in the question (longest match wins)."""
    q = question_key(question)
    found: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        for key in name_keys(name):
            pos = q.find(f" {key} ")
            if pos != -1:
                found.append((pos, pos + len(key) + 1, {"name": name, "labels": row.get("labels") or []}))
                break
    # Longest names first; drop names that sit inside an already-matched longer name.
    found.sort(key=lambda item: item[1] - item[0], reverse=True)
    chosen: list[tuple[int, int, dict[str, Any]]] = []
    for start, end, entity in found:
        if all(end <= s or start >= e for s, e, _ in chosen):
            chosen.append((start, end, entity))
    chosen.sort(key=lambda item: item[0])          # order of mention
    return [entity for _, _, entity in chosen]


# ── Queries ───────────────────────────────────────────────────────────────────

MAP_DOMAINS_QUERY = """
// pra_map_domains
MATCH (d:Domain)
OPTIONAL MATCH (d)-[:CONTAINS]->(f:Function)
OPTIONAL MATCH (d)-[:CONTAINS]->(s:SupportingDomain)
RETURN d.name AS domain, d.description AS description,
       collect(DISTINCT f.name) AS functions, collect(DISTINCT s.name) AS supporting
"""

MAP_SUPPORT_QUERY = """
// pra_map_support
MATCH (s:SupportingDomain)-[r:PROVIDES_TO_SUPPORTING|DEPENDS_ON_SUPPORTING]-(f:Function)<-[:CONTAINS]-(d:Domain)
WITH s, d, f, r, startNode(r) = s AS from_sd
RETURN s.name AS supporting_domain, d.name AS stage,
       collect(DISTINCT CASE WHEN (type(r) = 'PROVIDES_TO_SUPPORTING' AND from_sd)
                               OR (type(r) = 'DEPENDS_ON_SUPPORTING' AND NOT from_sd)
                             THEN f.name END) AS supports,
       collect(DISTINCT CASE WHEN type(r) = 'DEPENDS_ON_SUPPORTING' AND from_sd
                             THEN f.name END) AS depends_on
"""

PROFILE_NODE_QUERY = """
// profile_node
MATCH (n {name: $name})
WHERE n:Domain OR n:SupportingDomain
OPTIONAL MATCH (parent:Domain)-[:CONTAINS]->(n)
OPTIONAL MATCH (n)-[:CONTAINS]->(f:Function)
OPTIONAL MATCH (n)-[:CONTAINS]->(child:SupportingDomain)
OPTIONAL MATCH (n)-[:HAS_PURPOSE]->(p)
OPTIONAL MATCH (n)-[:HAS_RULE]->(ru)
RETURN n.name AS name, labels(n) AS labels, n.description AS description,
       collect(DISTINCT parent.name) AS layers,
       collect(DISTINCT f.name) AS functions,
       collect(DISTINCT child.name) AS supporting,
       collect(DISTINCT coalesce(p.description, p.name)) AS purposes,
       collect(DISTINCT coalesce(ru.description, ru.name)) AS rules
"""

# Links of a supporting domain (to journey functions and other supporting domains),
# or of a journey stage's functions (to supporting domains).
PROFILE_LINKS_QUERY = """
// profile_links
MATCH (n {name: $name})
WHERE n:Domain OR n:SupportingDomain
OPTIONAL MATCH (n)-[:CONTAINS]->(own:Function)
WITH n, collect(own) AS own_functions
WITH n, CASE WHEN size(own_functions) > 0 THEN own_functions ELSE [n] END AS members
UNWIND members AS m
MATCH (m)-[r:PROVIDES_TO_SUPPORTING|DEPENDS_ON_SUPPORTING]-(x)
WHERE x <> n
OPTIONAL MATCH (stage:Domain)-[:CONTAINS]->(x:Function)
RETURN m.name AS member, type(r) AS link, startNode(r) = m AS outgoing,
       labels(x) AS kind, x.name AS other, collect(DISTINCT stage.name) AS stages
"""


# ── Building the evidence ────────────────────────────────────────────────────

def _names(values: Any) -> list[str]:
    return [str(v).strip() for v in (values or []) if v is not None and str(v).strip()]


def _short(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 1].rstrip() + "…"


def _join(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    extra = len(items) - MAX_LIST
    text = "; ".join(items[:MAX_LIST])
    return text + (f"; (+{extra} more)" if extra > 0 else "")


def _node(name: str, label: str, description: str = "") -> Neo4jNode:
    props = {"name": name}
    if description:
        props["description"] = description
    return Neo4jNode(element_id=name, labels=[label], properties=props)


def _journey_sort_key(name: str) -> tuple[int, str]:
    return (JOURNEY_ORDER.index(name), "") if name in JOURNEY_ORDER else (len(JOURNEY_ORDER), name)


async def retrieve_pra_map(client) -> Neo4jGraphEvidence:
    """Complete PRA map. Never raises: on any error, returns empty evidence (old behaviour)."""
    try:
        evidence = await _pra_map(client)
        logger.info("graph_pra_map", entities=evidence.result_count)
        return evidence
    except Exception as exc:
        logger.warning("graph_pra_map_failed", error=str(exc))
        return Neo4jGraphEvidence()


async def _pra_map(client) -> Neo4jGraphEvidence:
    """Journey stages (in order), supporting layers, who supports which stage."""
    domain_rows, support_rows = await asyncio.gather(
        client.execute_read_query(MAP_DOMAINS_QUERY),
        client.execute_read_query(MAP_SUPPORT_QUERY),
    )
    nodes: dict[str, Neo4jNode] = {}
    stages = sorted((r for r in domain_rows if _names(r.get("functions"))),
                    key=lambda r: _journey_sort_key(str(r.get("domain"))))
    layers = sorted((r for r in domain_rows if _names(r.get("supporting"))), key=lambda r: str(r.get("domain")))

    lines = ["PRA STRUCTURE (complete map from the knowledge graph)", "",
             f"Payment journey stages, in order ({len(stages)}):"]
    for i, row in enumerate(stages, start=1):
        name = str(row["domain"])
        nodes[name] = _node(name, "Domain", _short(row.get("description")))
        functions = _names(row.get("functions"))
        for f in functions:
            nodes.setdefault(f, _node(f, "Function"))
        lines.append(f"  {i}. {name} — functions: {_join(functions)}")

    total_sd = sum(len(_names(r.get("supporting"))) for r in layers)
    lines += ["", f"Supporting layers and their supporting domains ({len(layers)} layers, {total_sd} supporting domains):"]
    for row in layers:
        name = str(row["domain"])
        nodes.setdefault(name, _node(name, "Domain", _short(row.get("description"))))
        supporting = _names(row.get("supporting"))
        for s in supporting:
            nodes.setdefault(s, _node(s, "SupportingDomain"))
        lines.append(f"  - {name}: {_join(supporting)}")

    supports: dict[str, dict[str, list[str]]] = {}
    for row in support_rows:
        sd, stage = str(row.get("supporting_domain") or ""), str(row.get("stage") or "")
        served = _names(row.get("supports"))
        if sd and stage and served:
            supports.setdefault(sd, {})[stage] = served
    if supports:
        lines += ["", "Journey stages each supporting domain supports (the functions it serves):"]
        for sd in sorted(supports):
            parts = [f"{stage} ({', '.join(fns[:3])}{', …' if len(fns) > 3 else ''})"
                     for stage, fns in sorted(supports[sd].items(), key=lambda kv: _journey_sort_key(kv[0]))]
            lines.append(f"  - {sd} → {'; '.join(parts)}")

    return Neo4jGraphEvidence(
        query=MAP_DOMAINS_QUERY + "\n---\n" + MAP_SUPPORT_QUERY,
        results=list(nodes.values()),
        result_count=len(nodes),
        summary="\n".join(lines),
    )


async def _profile(client, name: str) -> tuple[list[str], dict[str, Neo4jNode]]:
    node_rows, link_rows = await asyncio.gather(
        client.execute_read_query(PROFILE_NODE_QUERY, name=name),
        client.execute_read_query(PROFILE_LINKS_QUERY, name=name),
    )
    if not node_rows:
        return [], {}
    row = node_rows[0]
    labels = _names(row.get("labels"))
    is_supporting = "SupportingDomain" in labels
    functions, children = _names(row.get("functions")), _names(row.get("supporting"))
    kind = ("Supporting domain" if is_supporting
            else "Payment journey stage" if functions else "Supporting layer")

    nodes: dict[str, Neo4jNode] = {name: _node(name, "SupportingDomain" if is_supporting else "Domain",
                                               _short(row.get("description")))}
    lines = [f"{name} ({kind})"]
    if row.get("description"):
        lines.append(f"  description: {_short(row['description'])}")
    layers = [l for l in _names(row.get("layers")) if l != name]
    if layers:
        lines.append(f"  part of layer: {', '.join(layers)}")
    purposes = [_short(p) for p in _names(row.get("purposes"))]
    if purposes:
        lines.append(f"  purpose: {' / '.join(purposes[:2])}")
    rules = [_short(r) for r in _names(row.get("rules"))]
    if rules:
        lines.append(f"  rules: {_join(rules)}")
    if functions:
        lines.append(f"  functions: {_join(functions)}")
        for f in functions:
            nodes.setdefault(f, _node(f, "Function"))
    if children:
        lines.append(f"  supporting domains: {_join(children)}")
        for c in children:
            nodes.setdefault(c, _node(c, "SupportingDomain"))

    # Read every link from the point of view of this domain (or its functions).
    supports_fn: dict[str, list[str]] = {}      # journey function -> its stage(s)
    depends_fn: dict[str, list[str]] = {}
    supports_sd: list[str] = []
    depends_sd: list[str] = []
    supported_by: dict[str, list[str]] = {}    # supporting domain -> our functions it serves
    for link in link_rows:
        other = str(link.get("other") or "")
        if not other:
            continue
        other_is_sd = "SupportingDomain" in _names(link.get("kind"))
        outgoing = bool(link.get("outgoing"))
        provides = link.get("link") == "PROVIDES_TO_SUPPORTING"
        # "member serves other" when member provides to it, or other depends on member.
        member_serves_other = (provides and outgoing) or (not provides and not outgoing)
        member = str(link.get("member") or "")
        nodes.setdefault(other, _node(other, "SupportingDomain" if other_is_sd else "Function"))

        if is_supporting:
            stages = _names(link.get("stages"))
            if other_is_sd:
                (supports_sd if member_serves_other else depends_sd).append(other)
            else:
                (supports_fn if member_serves_other else depends_fn).setdefault(other, stages)
        elif other_is_sd and not member_serves_other:
            supported_by.setdefault(other, []).append(member)

    def fn_list(mapping: dict[str, list[str]]) -> str:
        return _join([f"{f} ({', '.join(s)} stage)" if s else f for f, s in mapping.items()])

    if supports_fn:
        stages = sorted({s for v in supports_fn.values() for s in v}, key=_journey_sort_key)
        if stages:
            lines.append(f"  supports journey stages: {', '.join(stages)}")
        lines.append(f"  supports journey functions: {fn_list(supports_fn)}")
    if depends_fn:
        lines.append(f"  depends on journey functions: {fn_list(depends_fn)}")
    if supports_sd:
        lines.append(f"  supports supporting domains: {_join(supports_sd)}")
    if depends_sd:
        lines.append(f"  depends on supporting domains: {_join(depends_sd)}")
    if supported_by:
        lines.append("  supported by supporting domains: " + _join(
            [f"{sd} (for {', '.join(dict.fromkeys(fns))})" for sd, fns in sorted(supported_by.items())]))
    return lines, nodes


async def retrieve_domain_profiles(client, entities: list[dict[str, Any]]) -> Neo4jGraphEvidence:
    """Profiles of the named domains. Never raises: on any error, returns empty evidence."""
    try:
        evidence = await _domain_profiles(client, entities)
        logger.info("graph_domain_profiles", domains=[e["name"] for e in entities[:MAX_PROFILES]],
                    entities=evidence.result_count)
        return evidence
    except Exception as exc:
        logger.warning("graph_domain_profiles_failed", error=str(exc))
        return Neo4jGraphEvidence()


async def _domain_profiles(client, entities: list[dict[str, Any]]) -> Neo4jGraphEvidence:
    """Profile of every named domain / supporting domain (up to MAX_PROFILES)."""
    names = [str(e["name"]) for e in entities[:MAX_PROFILES]]
    profiles = await asyncio.gather(*(_profile(client, n) for n in names))
    lines: list[str] = ["PRA DOMAIN PROFILES (from the knowledge graph)"]
    nodes: dict[str, Neo4jNode] = {}
    for profile_lines, profile_nodes in profiles:
        if profile_lines:
            lines += [""] + profile_lines
            for key, node in profile_nodes.items():
                nodes.setdefault(key, node)
    if not nodes:
        return Neo4jGraphEvidence()
    return Neo4jGraphEvidence(
        query=PROFILE_NODE_QUERY + "\n---\n" + PROFILE_LINKS_QUERY,
        results=list(nodes.values()),
        result_count=len(nodes),
        summary="\n".join(lines),
    )
