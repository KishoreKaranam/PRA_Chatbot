"""GraphDB HTTP/SPARQL adapter."""

from app.infrastructure.knowledge_graph.graphdb.client import GraphDBClient, get_graphdb_client

__all__ = ["GraphDBClient", "get_graphdb_client"]
