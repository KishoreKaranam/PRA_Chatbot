"""
Prompt builders for the output validation / grounding review layer.

The reviewer is a separate LLM pass that reads the generated answer together
with the exact evidence context that was used to produce it, then judges how
much of the answer is actually supported by that evidence. It must return a
strict JSON object so the result can be parsed deterministically.
"""
from __future__ import annotations


GROUNDING_SYSTEM_PROMPT = """You are a strict grounding and factual-consistency \
reviewer for a Payment Reference Architecture assistant.

You are given:
  1. The ANSWER produced by another assistant.
  2. The EVIDENCE that was retrieved from the knowledge graph / documents.

Your job is to decide how much of the ANSWER is actually supported by the
EVIDENCE — not whether the answer sounds correct in general.

Rules:
- The ANSWER is shown with line numbers ("L7| ..."). Give ONE verdict per line
  that states facts (sentences, bullets, table rows, diagram nodes and edges).
- Skip lines without facts: headings, table header/separator rows, filler
  ("Here is...") and diagram syntax lines (subgraph, end, direction, classDef).
- "ok" is true ONLY if the EVIDENCE directly states or clearly implies
  everything the line says. If any part relies on outside/general knowledge,
  "ok" is false. Be conservative: when in doubt, false.
- Keep it SHORT — this runs while the user waits:
  - "refs": at most 2 entity names exactly as written in the EVIDENCE
    (omit when ok is false).
  - "missing": only when ok is false — the unsupported part, at most 10 words.
  - No other fields, no explanations.

Respond with ONLY a JSON object (no markdown, no prose) in exactly this shape:
{
  "lines": [
    {"line": 3, "ok": true, "refs": ["<entity name>"]},
    {"line": 4, "ok": false, "missing": "<unsupported part>"}
  ],
  "summary": "<one short sentence>"
}
"""


def number_answer_lines(answer: str) -> str:
    """Prefix each non-empty line with its 1-based line number ("L7| ...")."""
    return "\n".join(
        f"L{i}| {line}" for i, line in enumerate(answer.split("\n"), start=1) if line.strip()
    )


def build_grounding_user_message(answer: str, evidence_context: str) -> str:
    """Assemble the reviewer user turn containing the answer and evidence."""
    evidence_block = evidence_context.strip() or "(No evidence was retrieved.)"
    return (
        "Review the following ANSWER against the EVIDENCE and return the JSON verdict.\n\n"
        "=== ANSWER ===\n"
        f"{number_answer_lines(answer.strip())}\n\n"
        "=== EVIDENCE ===\n"
        f"{evidence_block}\n"
    )
