"""Deep probe of PRA_V2 - get all predicates, sample instances with labels."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.core.settings import get_settings
get_settings.cache_clear()
from app.infrastructure.knowledge_graph.graphdb.client import GraphDBClient

PRA2_NS = "https://example.org/pra/payments#"

async def probe():
    c = GraphDBClient()

    # All predicates in pra/payments namespace
    r = await c.select("""
SELECT DISTINCT ?p WHERE {
  ?s ?p ?o .
  FILTER(STRSTARTS(STR(?p), "https://example.org/pra/payments#"))
}
ORDER BY ?p
""")
    print("PRA2 predicates:")
    for b in r:
        print(" ", b["p"]["value"].split("#")[-1])

    # Sample instances of each class with labels
    r2 = await c.select("""
SELECT ?cls (COUNT(?x) AS ?cnt) WHERE {
  ?x a ?cls .
  FILTER(STRSTARTS(STR(?cls), "https://example.org/pra/payments#"))
}
GROUP BY ?cls
ORDER BY DESC(?cnt)
""")
    print("\nClass instance counts:")
    for b in r2:
        print(f"  {b['cls']['value'].split('#')[-1]}: {b['cnt']['value']}")

    # Sample BusinessFunction instances
    r3 = await c.select("""
SELECT ?x ?label ?desc WHERE {
  ?x a <https://example.org/pra/payments#BusinessFunction> .
  OPTIONAL { ?x rdfs:label ?label }
  OPTIONAL { ?x <https://example.org/pra/payments#descriptionText> ?desc }
}
LIMIT 5
""")
    print("\nSample BusinessFunction instances:")
    for b in r3:
        label = b.get("label", {}).get("value", "?")
        desc = b.get("desc", {}).get("value", "?")[:80]
        uri = b["x"]["value"].split("/")[-1]
        print(f"  {uri}: {label} | {desc}")

    # Sample Activity instances
    r4 = await c.select("""
SELECT ?x ?label ?desc WHERE {
  ?x a <https://example.org/pra/payments#Activity> .
  OPTIONAL { ?x rdfs:label ?label }
  OPTIONAL { ?x <https://example.org/pra/payments#descriptionText> ?desc }
}
LIMIT 5
""")
    print("\nSample Activity instances:")
    for b in r4:
        label = b.get("label", {}).get("value", "?")
        uri = b["x"]["value"].split("/")[-1]
        print(f"  {uri}: {label}")

    # All unique predicates (any namespace)
    r5 = await c.select("""
SELECT DISTINCT ?p WHERE { ?s ?p ?o }
ORDER BY ?p
""")
    print(f"\nAll predicates ({len(r5)}):")
    for b in r5:
        print(" ", b["p"]["value"])

    # Check if FTS index exists
    r6 = await c.select("""
SELECT ?connector WHERE {
  ?connector a <http://www.ontotext.com/connectors/lucene#Connector>
}
""")
    print("\nLucene connectors:", [b["connector"]["value"] for b in r6] if r6 else "None")

    await c._client.aclose()

asyncio.run(probe())
