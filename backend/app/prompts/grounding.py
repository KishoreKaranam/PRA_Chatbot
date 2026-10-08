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
- Break the ANSWER into atomic, verifiable claims (one fact per claim).
- Ignore pure formatting, headings, questions back to the user, generic
  filler ("Let me explain...") and meta commentary — do not count these as claims.
- A claim is "supported" ONLY if the EVIDENCE directly states or clearly implies it.
- If a claim relies on outside/general knowledge not present in the EVIDENCE,
  mark it "supported": false.
- Be conservative: when in doubt, mark as not supported.

Respond with ONLY a JSON object (no markdown, no prose) in exactly this shape:
{
  "claims": [
    {
      "claim": "<atomic statement from the answer>",
      "supported": true,
      "evidence_refs": ["<label or uri of supporting evidence>"],
      "note": "<short reason>"
    }
  ],
  "summary": "<one or two sentence reviewer summary>"
}
"""


def build_grounding_user_message(answer: str, evidence_context: str) -> str:
    """Assemble the reviewer user turn containing the answer and evidence."""
    evidence_block = evidence_context.strip() or "(No evidence was retrieved.)"
    return (
        "Review the following ANSWER against the EVIDENCE and return the JSON verdict.\n\n"
        "=== ANSWER ===\n"
        f"{answer.strip()}\n\n"
        "=== EVIDENCE ===\n"
        f"{evidence_block}\n"
    )
