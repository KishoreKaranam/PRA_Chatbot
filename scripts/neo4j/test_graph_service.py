"""Direct read-only check for Neo4j graph retrieval."""
from __future__ import annotations

import asyncio
import json
from app.infrastructure.knowledge_graph.neo4j.client import Neo4jClient
from app.infrastructure.retrieval.neo4j import Neo4jGraphRetrievalService


async def main() -> None:
    client = Neo4jClient()
    test_results = []

    test_questions = [
        "What are the main business functions in PRA?",
        "What activities are associated with business functions?",
        "What business rules govern functions?",
        "What are the preconditions and postconditions?",
        "Which functions depend on each other?",
    ]

    try:
        service = Neo4jGraphRetrievalService(client)
        
        for i, question in enumerate(test_questions):
            print("=" * 40)
            print(f"TEST {i+1}:")
            print(f"QUESTION: {question}")
            print("=" * 40)

            status = "ERROR"
            error_message = ""

            try:
                evidence = await service.retrieve(question)

                # Extract detected components from the evidence object
                pattern_name = evidence._pattern_name
                source_label = evidence._source_label
                rel_type = evidence._relationship_type
                target_label = evidence._target_label

                cypher_params = {"limit": service._max_results}

                print(f"1. Detected Intent/Pattern: {pattern_name or 'None'}")
                print(f"2. Source Label: {source_label or 'N/A'}")
                print(f"3. Relationship Type(s): {rel_type or 'N/A'}")
                print(f"4. Target Label: {target_label or 'N/A'}")
                print(f"5. Exact Cypher Query/Queries:\n```cypher\n{evidence.query}\n```")
                print(f"6. Parameters: {json.dumps(cypher_params, indent=2)}")
                print(f"7. Total Result Count: {evidence.result_count}")

                if evidence.result_count == 0:
                    print("NO RESULTS")
                    status = "NO RESULTS"
                else:
                    print("8. Sample Normalized Relationships (up to 5):")
                    for relationship in evidence.relationships[:5]:
                        print(json.dumps(relationship.model_dump(), ensure_ascii=True, default=str))
                    status = "PASS"
                
                if pattern_name == "pre_and_postconditions":
                    pre_count = sum(1 for r in evidence.relationships if r.type == "hasPrecondition")
                    post_count = sum(1 for r in evidence.relationships if r.type == "hasPostcondition")
                    print(f"   - hasPrecondition result count: {pre_count}")
                    print(f"   - hasPostcondition result count: {post_count}")

            except Exception as exc:
                error_message = str(exc)
                print(f"Error encountered: {error_message}")
                status = "ERROR"
            
            test_results.append({
                "question": question,
                "pattern": pattern_name if 'pattern_name' in locals() else "N/A",
                "relationships": rel_type if 'rel_type' in locals() else "N/A",
                "result_count": evidence.result_count if 'evidence' in locals() else 0,
                "status": status
            })
            print("\n")

        # Summary Table
        print("=" * 40)
        print("SUMMARY TABLE")
        print("=" * 40)
        print(f"{'Question':<50} | {'Pattern':<30} | {'Relationship(s)':<25} | {'Result Count':<12} | {'Status':<10}")
        print("-" * 50 + " | " + "-" * 30 + " | " + "-" * 25 + " | " + "-" * 12 + " | " + "-" * 10)
        for res in test_results:
            print(f"{res['question']:<50} | {str(res['pattern']):<30} | {str(res['relationships']):<25} | {res['result_count']:<12} | {res['status']:<10}")
        print("\n")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
