# Script 3: tools available to the LLM agent (script2).
# Each tool has a JSON schema (for Anthropic) and a plain python function
# that performs the actual work. call_tool() dispatches by tool name.

import os
from anthropic.types import ToolParam
from neo4j import GraphDatabase
from config.settings import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from utils.logger import get_logger
from utils.file_parser import parse_file

logger = get_logger(__name__)

# Single shared Neo4j driver, created once and reused by all tool calls.
_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# --- Tool schemas passed to the Anthropic agent ---
TOOL_SCHEMAS: list[ToolParam] = [
    {
        "name": "read_file",
        "description": "Read and parse the text content of a stored file by its path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full path to the stored file."},
                "extension": {"type": "string", "description": "File extension, e.g. 'pdf', 'docx'."},
            },
            "required": ["path", "extension"],
        },
    },
    {
        "name": "query_graph",
        "description": "Run a read-only Cypher query against the Neo4j database and return records.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cypher": {"type": "string", "description": "Cypher query to run."},
                "params": {"type": "object", "description": "Optional query parameters."},
            },
            "required": ["cypher"],
        },
    },
    {
        "name": "write_graph",
        "description": "Run a write Cypher query against Neo4j to create/update nodes and relationships.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cypher": {"type": "string", "description": "Cypher write query to run."},
                "params": {"type": "object", "description": "Optional query parameters."},
            },
            "required": ["cypher"],
        },
    },
]


def tool_read_file(path, extension):
    """Read a stored file from disk and parse it into plain text."""
    if not os.path.exists(path):
        logger.info(f"read_file failed, missing path: {path}")
        return {"ok": False, "error": "file not found"}

    try:
        text = parse_file(path, extension)
        logger.info(f"read_file ok: {path}")
        return {"ok": True, "text": text}
    except Exception as e:
        logger.info(f"read_file parse error for {path}: {e}")
        return {"ok": False, "error": str(e)}


def tool_query_graph(cypher, params=None):
    """Run a read Cypher query and return the resulting rows as dicts."""
    params = params or {}
    try:
        with _driver.session() as session:
            result = session.run(cypher, params)
            rows = [record.data() for record in result]
        logger.info(f"query_graph ok, rows returned: {len(rows)}")
        return {"ok": True, "rows": rows}
    except Exception as e:
        logger.info(f"query_graph error: {e}")
        return {"ok": False, "error": str(e)}


def tool_write_graph(cypher, params=None):
    """Run a write Cypher query and return a short summary.

    Covers everything Neo4j's SummaryCounters can report for a write query:
    creation and deletion of nodes/relationships, property updates, and
    label changes (e.g. a MERGE ... SET that only changes properties on an
    already-existing node, or a query that removes nodes/relationships/labels).
    """
    params = params or {}
    try:
        with _driver.session() as session:
            result = session.run(cypher, params)
            summary = result.consume()
        counters = summary.counters
        logger.info(
            f"write_graph ok, nodes_created={counters.nodes_created}, "
            f"nodes_deleted={counters.nodes_deleted}, "
            f"rels_created={counters.relationships_created}, "
            f"rels_deleted={counters.relationships_deleted}, "
            f"properties_set={counters.properties_set}, "
            f"labels_added={counters.labels_added}, "
            f"labels_removed={counters.labels_removed}"
        )
        return {
            "ok": True,
            "nodes_created": counters.nodes_created,
            "nodes_deleted": counters.nodes_deleted,
            "relationships_created": counters.relationships_created,
            "relationships_deleted": counters.relationships_deleted,
            "properties_set": counters.properties_set,
            "labels_added": counters.labels_added,
            "labels_removed": counters.labels_removed,
        }
    except Exception as e:
        logger.info(f"write_graph error: {e}")
        return {"ok": False, "error": str(e)}


# Maps tool name (as called by the LLM) to the actual python function.
TOOL_FUNCTIONS = {
    "read_file": tool_read_file,
    "query_graph": tool_query_graph,
    "write_graph": tool_write_graph,
}


def call_tool(name, tool_input):
    """Dispatch a tool call by name with its input dict. Returns a result dict.

    Never raises: if the tool name is unknown or the arguments don't match
    the function's signature (e.g. the model omitted a required field),
    this returns an error dict instead of crashing the request, so the
    agent loop can see the error and try again.
    """
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        logger.info(f"unknown tool requested: {name}")
        return {"ok": False, "error": f"unknown tool: {name}"}

    try:
        return func(**tool_input)
    except TypeError as e:
        logger.info(f"invalid arguments for tool '{name}': {e}")
        return {"ok": False, "error": f"invalid arguments for tool '{name}': {e}"}
