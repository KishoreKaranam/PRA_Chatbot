"""Graph backend package — supports GraphDB (HTTP) and rdflib (in-memory)."""
from app.infrastructure.knowledge_graph.base import GraphBackend  # noqa: F401
from app.infrastructure.knowledge_graph.graphdb.client import get_graphdb_client  # noqa: F401
