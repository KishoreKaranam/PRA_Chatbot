"""Prompts and user-facing clarification text for conversation processing."""


def build_node_context_resolution_prompt(history_text: str, raw: str) -> str:
    return (
        f"Conversation history:\n{history_text}\n\n"
        f'New user message: "{raw}"\n\n'
        "Tasks (answer in JSON only — no extra text):\n"
        "1. Is this a follow-up to the conversation above? (true/false)\n"
        "2. Rewrite the message as a fully self-contained question, resolving all "
        "pronouns and references using the history. "
        "If no rewrite is needed, return the original message.\n\n"
        'Respond ONLY with: {"is_followup": true|false, "rewritten": "<question>"}'
    )


def build_pipeline_context_resolution_prompt(history_text: str, raw_question: str) -> str:
    return (
        f"Conversation history:\n{history_text}\n\n"
        f'New user message: "{raw_question}"\n\n'
        "Tasks (answer in JSON only — no extra text):\n"
        "1. Is this a follow-up to the conversation above? (true/false)\n"
        "2. If it is a follow-up, rewrite it as a fully self-contained question "
        "resolving all pronouns (it, they, those, that) and abbreviations using "
        "the conversation history.\n"
        "   If it is NOT a follow-up, set rewritten to the original question.\n\n"
        'Respond ONLY with: {"is_followup": true/false, "rewritten": "<question>"}'
    )


def build_node_clarification_message(question: str) -> str:
    return (
        f'I\'d like to help, but your question "{question}" is a bit brief. '
        "Could you tell me more? For example:\n"
        "- Are you asking about a specific **payment domain** (e.g. Card Payments, SEPA SCT)?\n"
        "- A **business function** (e.g. Authorization, Settlement, Fraud Check)?\n"
        "- A **business rule or activity**?\n"
        "- Or something else in the Payment Reference Architecture?"
    )


def build_pipeline_clarification_message(question: str) -> str:
    return (
        f'I\'d like to help, but your question "{question}" is a bit brief. '
        "Could you tell me more? For example:\n"
        "- Are you asking about a specific **payment domain** (e.g. Card Payments, SEPA)?\n"
        "- A **business function** (e.g. Authorization, Settlement)?\n"
        "- A **rule or activity**?\n"
        "- Or something else in the Payment Reference Architecture?"
    )


def build_insufficient_evidence_message(question: str) -> str:
    return (
        f'I searched the PRA knowledge graph for "{question}" but could not find '
        "sufficiently confident evidence. You could try:\n"
        "- Rephrasing with more specific PRA terminology\n"
        "- Asking about a specific domain, function, or payment scheme\n"
        "- Lowering the confidence threshold in the sidebar settings"
    )
