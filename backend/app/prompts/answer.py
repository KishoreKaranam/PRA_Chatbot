"""Answer-generation prompt text and composition."""

STYLE_INSTRUCTIONS = {
    "business": (
        "Answer in clear business language. Avoid jargon. "
        "Use bullet points where helpful. Target a payments business audience."
    ),
    "technical": (
        "Answer with technical precision. Include ontology class names, "
        "property URIs, and graph relationships where relevant."
    ),
    "concise": (
        "Be brief and to the point. Use short sentences and avoid lengthy explanations. "
        "When the question asks to list items (e.g. domains, functions, rules), "
        "you MUST include every item retrieved — do not truncate or omit any entries. "
        "Keep descriptions per item to one short phrase."
    ),
    "detailed": (
        "Provide a thorough, comprehensive answer. Include examples from the "
        "retrieved context, relationships, and relevant activities or rules."
    ),
}

INTENT_GUIDANCE = {
    "definition": "The user wants a clear definition. Lead with a one-sentence definition, then expand.",
    "list": "The user wants a complete list. Return EVERY item found — do not truncate.",
    "comparison": "The user wants a comparison. Use a side-by-side structure.",
    "exploratory": "Provide a thorough, well-structured exploration of the topic.",
    "vague": "The question is broad. Cover the most likely interpretation first.",
    "diagram": "The user wants a visual picture (architecture, process/workflow, or other diagram). Respond with a Mermaid diagram (see DIAGRAM RULES).",
}

# Appended to the system prompt only when intent == "diagram".
# Forces the model to emit a single renderable Mermaid code block instead of
# ASCII art, so the frontend can render it as a downloadable picture.
# The diagram type adapts to the request: an ARCHITECTURE view for
# architecture/structure questions, or a PROCESS FLOW for process/workflow
# questions.
DIAGRAM_RULES = (
    "\nDIAGRAM RULES (intent = diagram):\n"
    "- Output the diagram as a SINGLE fenced Mermaid code block: start with a line "
    "containing exactly ```mermaid and end with a line containing exactly ```.\n"
    "- NEVER draw ASCII/ASCII-art boxes, dashes, pipes, or dotted lines. Use Mermaid only.\n"
    "- CHOOSE THE DIAGRAM TYPE FROM THE QUESTION:\n"
    "  • If the user asks for an ARCHITECTURE, structure, components, topology, or layout, "
    "produce an ARCHITECTURE diagram: group components into `subgraph` boxes that represent "
    "PRA domains, business functions, or architectural layers, and draw edges for structural "
    "relationships (dependencies, ownership, supporting domains, applicability) — NOT temporal "
    "order.\n"
    "  • If the user asks for a PROCESS, workflow, flow, sequence, or steps, produce a PROCESS "
    "FLOW diagram: use `flowchart LR` (or `TB`) with nodes for each step and directed edges "
    "showing the order of execution from start to finish. Use decision nodes `{\"...\"}` for "
    "branches where the evidence describes conditions.\n"
    "  • For any other visual request, pick whichever of the two best fits the evidence.\n"
    "- Use `flowchart LR` (or `TB`) as the base syntax.\n"
    "- Base every group, node, and edge strictly on the retrieved PRA evidence. Do not invent "
    "components, groups, steps, or relationships that are not supported by the context.\n"
    "- Use short, human-readable labels from the graph (node labels/descriptions), not URIs "
    "or internal element IDs.\n"
    "- Keep every label SHORT: at most 3-4 words (about 24 characters). Shorten long names "
    "to a recognisable term, use standard abbreviations (SCT, SDD, RTGS, etc.), and drop "
    "filler words. Put full detail in the explanation after the diagram, not inside nodes.\n"
    "- If a label truly cannot be shortened below ~24 characters, break it across lines with "
    "`<br/>` inside the quotes (e.g. `A[\"Applicability<br/>Assessment\"]`) so text never "
    "overflows the node.\n"
    "- Keep node and subgraph IDs simple (alphanumeric) and put descriptive text in the label, "
    "e.g. `subgraph Payments[\"Payments Domain\"]` and `A[\"Payment Capture\"]`.\n"
    "- ALWAYS wrap every node and subgraph label in straight double quotes, e.g. "
    "`A[\"Direct Debit\"]`. Never use curly/smart quotes. Never put parentheses ( ), "
    "square brackets, pipes |, semicolons, or the words `end`/`subgraph` INSIDE a label — "
    "replace them with a space or a dash so the diagram always parses.\n"
    "- Every `subgraph` MUST be closed with its own `end` line. Give each node a unique, "
    "stable alphanumeric ID and reuse that ID when drawing edges.\n"
    "- After the code block, add a brief one or two sentence explanation of the diagram.\n"
    "- If the evidence is insufficient to build a meaningful diagram, say so instead of guessing.\n"
)



def build_system_prompt(
    configured_prompt: str,
    style_instruction: str,
    intent: str,
    is_followup: bool,
) -> str:
    intent_guidance = INTENT_GUIDANCE.get(intent, "")
    followup_note = (
        "\nCONVERSATION CONTEXT: This is a follow-up question. "
        "Prior turns are included as conversation history above. "
        "Build on your previous answers — do not repeat already-given information. "
        "Resolve any pronouns (it, they, those) from the conversation history.\n"
        if is_followup else
        "\nCONVERSATION CONTEXT: This is the start of a new conversation.\n"
    )

    diagram_rules = DIAGRAM_RULES if intent == "diagram" else ""

    return (
        f"{configured_prompt}\n\n"
        f"Answer style: {style_instruction}\n"
        f"Intent detected: {intent_guidance}\n"
        f"{followup_note}\n"
        f"{diagram_rules}"
        "INTERNAL MONOLOGUE (not for output) — before answering, reason through:\n"
        "  1. What is the user actually asking? (resolve any references)\n"
        "  2. What relevant facts does the retrieved context contain?\n"
        "  3. Are there gaps? State them clearly.\n"
        "  4. Formulate a grounded, well-structured answer.\n\n"
        "RULES:\n"
        "- Only use facts from the retrieved context.\n"
        "- Answer directly in plain prose. Do NOT structure the response into labelled "
        "sections or bold headings such as 'Direct answer', 'Business meaning', "
        "'Scope / applicability', 'Dependencies / related domains', or 'Gaps / assumptions'. "
        "Write a single, cohesive answer; use a plain bullet list only when the user asked to "
        "list multiple items.\n"
        "- If the information is not available, simply state that the information is not available. Do NOT refer to the knowledge graph, Neo4j, SPARQL, FTS, similarity, graph, nodes, relationships, or any data source or retrieval mode when doing so.\n"
        "- Never mention the knowledge graph, Neo4j, SPARQL, FTS, similarity, graph, nodes, relationships, or retrieval modes in the user-facing answer. Present information as direct facts about the PRA.\n"
        "- Do NOT invent ontology terms, classes, or relationships.\n"
        "- Strongly prefer facts from PRIMARY GRAPH EVIDENCE over SUPPORTING EVIDENCE.\n"
        "- When PRIMARY GRAPH EVIDENCE contains a label or description, use that human-readable value in the answer. Do not display internal URIs, element IDs, or generated identifiers as business-facing names unless no human-readable label exists.\n"
        "- For relationship-specific questions, answer directly from the PRIMARY relationship evidence. Do not add unrelated facts from supporting evidence unless they are necessary to answer the question.\n"
        "- Distinguish facts directly supported by PRIMARY evidence from optional supporting information. Do not add unsupported explanatory details.\n"
        "- Report only relationships and entities actually present in the retrieved evidence. Do not claim all, every, or exactly N items are covered unless the evidence explicitly proves completeness.\n"
        "- Use PRA terminology exactly as it appears in the evidence.\n"
        "- Do not expose your internal monologue, chain-of-thought, or step-by-step reasoning. Provide only the final, user-facing answer.\n"
    )


def build_current_question_message(question: str, modes_label: str, context: str) -> str:
    return (
        f"Question: {question}\n\n"
        f"Retrieval modes used: {modes_label}\n\n"
        f"Retrieved context from the PRA knowledge graph:\n{context}\n\n"
        "Using chain of thought, reason through the context and provide your answer."
    )
