# Script 2: LLM agent that decides how to process stored files.
# It talks to Anthropic's Claude with tool-use, calling tools from script3
# until the model reports it has finished analyzing and storing the data.

import json
import anthropic
from anthropic import AnthropicFoundry
from anthropic.types import MessageParam, ToolResultBlockParam
from config.settings import (
    AZURE_FOUNDRY_BASE_URL,
    AZURE_FOUNDRY_API_KEY,
    ANTHROPIC_MODEL,
    ANTHROPIC_MAX_TOKENS,
    MAX_AGENT_STEPS,
)
from scripts.script3_tools import TOOL_SCHEMAS, call_tool
from utils.logger import get_logger

logger = get_logger(__name__)

#"Use provided query_graph tool to check what entities (graph nodes), their properties and relationships between them are existing in the Neo4j database. "
#"Then analyze content of new files together with data acquired from neo4j to find any new entities, properties and relationships. "
#"Check existing neo4j database schema and what types of relationships exist between entities. Try to reuse them to keep types of relationships consistent and on low count level. "
            
# System prompt describing the agent's role and expected workflow.

SYSTEM_PROMPT = (
    "You are a data ingestion agent for data related to Payments Reference Architecture (PRA). "
    "You receive a list of file paths containing data about PRA. "
    "For each file, use provided read_file tool to get its text content before the start of analyzing. "
    "When you call read_file tool to search for specific entity, check schema or high level structure first, not to miss existing items when will try to compare their label, name or description with specific text, while they may not have the exact one: this should prevent to create entity in wrong type or almost duplicate one. "
    "Then analyze content of new files to understand which part of extracted data may become part of entities, properties and relationships stored in neo4j database. "
    "If new data items and entities are not relevant to PRA, don't save them in the graph at all and skip them. "
    "Call query_graph tool when you need to know which part of the PRA related data extracted from new files is already present in the graph and what is new. You may check db schema, entities, their properties and relationships between them. "
    "Use provided write_graph tool to create or update entities and relationships according to new data from new files. "
    "Most of the entities are somehow semantically connected due to them being part of PRA, so don't leave new PRA entities not connected to main graph tree, "
    "but don't create relationships, which are not explicitly shown in the new data: if you are not sure about a relationship, don't create it. "
    "Don't create way too big requests in the batch to fail your response timeout: if you have many new entities and relationships, split them into multiple write_graph calls. "
    "Don't add entities or relationships that already exist in the graph: just skip them. But check if they need enchancement "
    "Don't save all provided data inside of the entities: save only name (if abbreviation add its expansion, if it is clearly stated in the document), description if available, otherwise just repeat the name, and source which is a file name with extension. "
    "All the rest of provided entity information (e.g. entity's purposes, rules, conditions and any other presented ones) should be stored as separate entities and be attached to main entity by relations. If there is a list of them, store and relate them to main entity separately. "
    "Proactively check if new data shows that some PRA entities should change their properties or relationships according to instructions in this prompt: update them accordingly, so we will keep graph database fresh. "
    "You may delete previously created relationships, which are contradicting to new data, but recheck carefully that there is no mistake. If still ambiguous, don't delete. "
    "When you are done processing all files, reply with a final plain text summary listing only which file paths were successfully processed, without calling any more tools. "
)

# ANTHROPIC_MODEL is used as the Foundry deployment name, which may differ from the raw model id.
client = AnthropicFoundry(api_key=AZURE_FOUNDRY_API_KEY, base_url=AZURE_FOUNDRY_BASE_URL)


def _build_initial_message(file_infos):
    """Turn the list of stored file infos into the first user message text."""
    lines = ["Process the following stored files:"]
    for info in file_infos:
        lines.append(f"- path: {info['path']}, extension: {info['extension']}")
    return "\n".join(lines)


def process_files(file_infos):
    """Run the agent loop over the given files.

    file_infos: list of dicts with keys 'path' and 'extension'.
    Returns dict: {"processed": [...paths...], "failed": [...paths...]}.
    """
    logger.info(f"agent started for {len(file_infos)} files")

    messages: list[MessageParam] = [{"role": "user", "content": _build_initial_message(file_infos)}]

    step = 0
    while step < MAX_AGENT_STEPS:
        step += 1

        try:
            response = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=ANTHROPIC_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
                stream=False,
            )
        except anthropic.APIError as e:
            # e.__cause__ carries the underlying httpx exception (e.g. DNS/TLS/refused), which "Connection error." alone hides.
            logger.info(f"agent stopped: Claude API call failed: {e} (cause: {e.__cause__!r})")
            return {"processed": [], "failed": [info["filename"] for info in file_infos]}

        # Collect the assistant's content so it can be added back to history.
        messages.append({"role": "assistant", "content": response.content})

        # Find any tool_use blocks the model asked for.
        tool_uses = [block for block in response.content if block.type == "tool_use"]

        if not tool_uses:
            # No more tools requested: the model gave its final summary.
            final_text = _extract_text(response.content)
            logger.info(f"agent finished after {step} step(s): {final_text}")
            break

        # Execute every requested tool call and feed results back to the model.
        tool_results: list[ToolResultBlockParam] = []
        for block in tool_uses:
            logger.info(f"agent calling tool '{block.name}' with input {block.input}")
            result = call_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop exhausted without a final answer: treat as failure for safety.
        logger.info("agent stopped: reached MAX_AGENT_STEPS without finishing")
        return {"processed": [], "failed": [info["filename"] for info in file_infos]}

    # Simple heuristic: a file counts as processed if its path is mentioned
    # in the model's final summary text. Matching is done on path (what the
    # model actually sees), but we report filenames since callers don't know paths.
    processed_infos = [info for info in file_infos if info["path"] in final_text]
    processed = [info["filename"] for info in processed_infos]
    failed = [info["filename"] for info in file_infos if info not in processed_infos]

    logger.info(f"agent result: processed={len(processed)}, failed={len(failed)}")
    return {"processed": processed, "failed": failed}


def _extract_text(content_blocks):
    """Join all plain text blocks from a response into one string."""
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(parts)
