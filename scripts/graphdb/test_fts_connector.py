"""Test the Lucene connector query directly."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.infrastructure.knowledge_graph.graphdb.client import GraphDBClient

# Note: luc: and luc-index: prefixes are already in COMMON_PREFIXES,
# so they must NOT be re-declared here
SPARQL = """
SELECT DISTINCT ?entity ?score WHERE {
  ?search a luc-index:pra_connector ;
          luc:query "payment" ;
          luc:entities ?entity .
  ?entity luc:score ?score .
}
ORDER BY DESC(?score)
LIMIT 5
"""

async def main():
    client = GraphDBClient()
    try:
        bindings = await client.select_get(SPARQL)
        print("Connector hits:", len(bindings))
        for b in bindings[:3]:
            entity = b.get("entity", {}).get("value", "").split("/")[-1]
            score  = b.get("score",  {}).get("value", "?")
            print(f"  {entity}  score={score}")
    except Exception as e:
        # Print the underlying HTTP error
        import traceback
        traceback.print_exc()
        cause = e.__context__
        if cause and hasattr(cause, "response"):
            print("HTTP status:", cause.response.status_code)
            print("Response:", cause.response.text[:400])
    finally:
        await client._client.aclose()

asyncio.run(main())
