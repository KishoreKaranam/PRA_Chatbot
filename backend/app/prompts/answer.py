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
}


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

    return (
        f"{configured_prompt}\n\n"
        f"Answer style: {style_instruction}\n"
        f"Intent detected: {intent_guidance}\n"
        f"{followup_note}\n"
        "INTERNAL MONOLOGUE (not for output) — before answering, reason through:\n"
        "  1. What is the user actually asking? (resolve any references)\n"
        "  2. What relevant facts does the retrieved context contain?\n"
        "  3. Are there gaps? State them clearly.\n"
        "  4. Formulate a grounded, well-structured answer.\n\n"
        "RULES:\n"
        "- Only use facts from the retrieved context.\n"
        "- If context is insufficient, say so explicitly.\n"
        "- Do NOT invent ontology terms, classes, or relationships.\n"
        "- Strongly prefer facts from PRIMARY GRAPH EVIDENCE over SUPPORTING EVIDENCE.\n"
        "- When Neo4j PRIMARY GRAPH EVIDENCE contains a node label or description, use that human-readable value in the answer. Do not display internal URIs, element IDs, or generated identifiers as business-facing names unless no human-readable label exists.\n"
        "- For relationship-specific questions, answer directly from the PRIMARY graph relationship evidence. Do not add unrelated facts from supporting FTS/similarity evidence unless they are necessary to answer the question.\n"
        "- Distinguish facts directly supported by PRIMARY graph evidence from optional supporting information. Do not add unsupported explanatory details.\n"
        "- Report only relationships and entities actually present in the retrieved evidence. Do not claim the graph contains all, every, or exactly N items unless the evidence explicitly proves completeness. Use wording such as 'The retrieved Neo4j evidence shows...' when the result is limited.\n"
        "- Do not mix supporting FTS or similarity results into an answer when PRIMARY Neo4j evidence already answers the question.\n"
        "- Cite which retrieval mode provided each fact (SPARQL / Neo4j / FTS / similarity).\n"
        "- Use PRA terminology exactly as it appears in the graph.\n"
        "- Do not expose your internal monologue, chain-of-thought, or step-by-step reasoning. Provide only the final, user-facing answer.\n"
    )


def build_current_question_message(question: str, modes_label: str, context: str) -> str:
    return (
        f"Question: {question}\n\n"
        f"Retrieval modes used: {modes_label}\n\n"
        f"Retrieved context from the PRA knowledge graph:\n{context}\n\n"
        "Using chain of thought, reason through the context and provide your answer."
    )
