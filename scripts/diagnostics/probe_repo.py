"""Probe PRA_V2 repository to understand its structure."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.core.settings import get_settings
get_settings.cache_clear()
from app.infrastructure.knowledge_graph.graphdb.client import GraphDBClient

async def probe():
    c = GraphDBClient()

    # 1. Total triples
    r = await c.select("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
    print("Total triples:", r[0]["n"]["value"] if r else "ERROR")

    # 2. All distinct rdf:type classes
    r2 = await c.select("SELECT DISTINCT ?cls WHERE { ?x a ?cls } ORDER BY ?cls")
    classes = [b["cls"]["value"] for b in r2]
    print(f"\nDistinct classes ({len(classes)}):")
    for cls in classes:
        print(" ", cls)

    # 3. All distinct namespaces from classes
    ns_set = set()
    for cls in classes:
        if "#" in cls:
            ns_set.add(cls.rsplit("#", 1)[0])
        elif "/" in cls:
            ns_set.add(cls.rsplit("/", 1)[0])
    print("\nNamespaces in use:")
    for ns in sorted(ns_set):
        print(" ", ns)

    # 4. Sample subjects
    r4 = await c.select("SELECT DISTINCT ?s WHERE { ?s a ?t } LIMIT 10")
    print("\nSample instance URIs:")
    for b in r4:
        print(" ", b["s"]["value"])

    # 5. All predicates used
    r5 = await c.select("SELECT DISTINCT ?p WHERE { ?s ?p ?o } ORDER BY ?p")
    print(f"\nPredicates ({len(r5)}):")
    for b in r5[:30]:
        print(" ", b["p"]["value"].split("#")[-1].split("/")[-1])

    # 6. Try pra:PRAElement specifically
    r6 = await c.select("SELECT (COUNT(*) AS ?n) WHERE { ?x a <https://example.org/pra#PRAElement> }")
    print("\npra:PRAElement count:", r6[0]["n"]["value"] if r6 else "0")

    # 7. Any rdfs:label triples?
    r7 = await c.select("SELECT ?s ?label WHERE { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?label } LIMIT 5")
    print("\nSample labels:")
    for b in r7:
        print(f"  {b['s']['value'].split('/')[-1]} -> {b['label']['value']}")

    await c._client.aclose()

asyncio.run(probe())
