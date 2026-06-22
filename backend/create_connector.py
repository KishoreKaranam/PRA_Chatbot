"""One-shot script: create the Lucene FTS connector in GraphDB for PRA_V2."""
import asyncio
import sys
import httpx

GRAPHDB_URL = "http://localhost:7200"
REPO        = "PRA_V2"

# Index rdfs:label, pra:descriptionText, pra:purposeText, rdfs:comment
# Full type list matching updated PRA_V2 (all concrete classes)
PRA_TYPES = [
    "https://example.org/pra/payments#BusinessFunction",
    "https://example.org/pra/payments#Activity",
    "https://example.org/pra/payments#BusinessRule",
    "https://example.org/pra/payments#Domain",
    "https://example.org/pra/payments#FunctionLink",
    "https://example.org/pra/payments#FunctionProvision",
    "https://example.org/pra/payments#FunctionDependency",
    "https://example.org/pra/payments#Condition",
    "https://example.org/pra/payments#InformationObject",
    "https://example.org/pra/payments#PaymentJourneyFunction",
    "https://example.org/pra/payments#SupportingFunction",
    "https://example.org/pra/payments#SupportingLayer",
    "https://example.org/pra/payments#SchemeType",
    "https://example.org/pra/payments#LifecyclePhase",
    "https://example.org/pra/payments#Mandate",
    "https://example.org/pra/payments#Notification",
    "https://example.org/pra/payments#Precondition",
    "https://example.org/pra/payments#Postcondition",
    # New classes added in updated PRA_V2
    "https://example.org/pra/payments#StatusInformation",
    "https://example.org/pra/payments#PaymentOrder",
    "https://example.org/pra/payments#FinancialArtifact",
    "https://example.org/pra/payments#DecisionArtifact",
    "https://example.org/pra/payments#ReportArtifact",
    "https://example.org/pra/payments#AccountInformation",
    "https://example.org/pra/payments#OperationalArtifact",
    "https://example.org/pra/payments#ReferenceData",
    "https://example.org/pra/payments#PaymentTransaction",
    "https://example.org/pra/payments#SettlementInstruction",
    "https://example.org/pra/payments#PaymentInstruction",
    "https://example.org/pra/payments#DocumentArtifact",
]

import json as _json
CONNECTOR_JSON = _json.dumps({
    "fields": [
        {"fieldName": "label",       "propertyChain": ["http://www.w3.org/2000/01/rdf-schema#label"],                          "indexed": True, "stored": True, "analyzed": True, "boost": 3.0},
        {"fieldName": "description", "propertyChain": ["https://example.org/pra/payments#descriptionText"],                    "indexed": True, "stored": True, "analyzed": True, "boost": 2.0},
        {"fieldName": "purposeText", "propertyChain": ["https://example.org/pra/payments#purposeText"],                        "indexed": True, "stored": True, "analyzed": True, "boost": 1.5},
        {"fieldName": "comment",     "propertyChain": ["http://www.w3.org/2000/01/rdf-schema#comment"],                        "indexed": True, "stored": True, "analyzed": True, "boost": 1.0},
    ],
    "types": PRA_TYPES,
    "languages": ["en", ""],
})

# SPARQL UPDATE using triple-quoted string literal
SPARQL = f"""\
PREFIX luc: <http://www.ontotext.com/connectors/lucene#>
PREFIX luc-index: <http://www.ontotext.com/connectors/lucene/instance#>

INSERT DATA {{
  luc-index:pra_connector luc:createConnector \"\"\"{CONNECTOR_JSON}\"\"\" .
}}
"""

async def main():
    url = f"{GRAPHDB_URL}/repositories/{REPO}/statements"
    async with httpx.AsyncClient(timeout=60) as client:
        # First drop any old connector with the same name
        drop_sparql = """\
PREFIX luc: <http://www.ontotext.com/connectors/lucene#>
PREFIX luc-index: <http://www.ontotext.com/connectors/lucene/instance#>
INSERT DATA {
  luc-index:pra_connector luc:dropConnector "" .
}
"""
        try:
            r = await client.post(url, data={"update": drop_sparql},
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
            print(f"Drop old connector: {r.status_code}")
        except Exception as e:
            print(f"Drop failed (OK if not existing): {e}")

        # Create new connector
        r = await client.post(url, data={"update": SPARQL},
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
        print(f"Create connector: HTTP {r.status_code}")
        if r.status_code not in (200, 204):
            print("Response:", r.text[:500])
            sys.exit(1)
        print("Connector created successfully!")

        # Verify: run a quick FTS query
        verify_sparql = """\
PREFIX luc: <http://www.ontotext.com/connectors/lucene#>
PREFIX luc-index: <http://www.ontotext.com/connectors/lucene/instance#>
PREFIX pra: <https://example.org/pra/payments#>
SELECT ?entity ?score ?label WHERE {
  ?search a luc-index:pra_connector ;
          luc:query "payment" ;
          luc:entities ?entity .
  ?entity luc:score ?score .
  OPTIONAL { ?entity rdfs:label ?label }
}
ORDER BY DESC(?score)
LIMIT 5
"""
        r2 = await client.get(
            f"{GRAPHDB_URL}/repositories/{REPO}",
            params={"query": verify_sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        import json
        data = r2.json()
        bindings = data.get("results", {}).get("bindings", [])
        print(f"\nFTS connector test — hits: {len(bindings)}")
        for b in bindings[:3]:
            score  = b.get("score", {}).get("value", "?")
            label  = b.get("label", {}).get("value", "?")[:60]
            entity = b.get("entity", {}).get("value", "?").split("/")[-1]
            print(f"  {entity}  score={score}  label={label}")

asyncio.run(main())
