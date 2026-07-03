"""Graph backend package — supports GraphDB (HTTP) and rdflib (in-memory)."""
from app.graphdb.base import GraphBackend  # noqa: F401
from app.graphdb.client import get_graphdb_client  # noqa: F401
