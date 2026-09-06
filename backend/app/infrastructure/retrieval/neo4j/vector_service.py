"""Isolated Neo4j vector retrieval service."""
from __future__ import annotations

from typing import Any, Callable

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.core.log_config import get_logger
from app.core.settings import get_settings
from app.models.schemas import SimilarityEvidence, SimilarityHit


logger = get_logger(__name__)


class Neo4jVectorRetrievalService:
    """Retrieve semantic matches from the existing Neo4j vector index."""

    INDEX_NAME = "pra_embedding_index"
    VECTOR_QUERY = """
    MATCH (node)
    SEARCH node IN (
        VECTOR INDEX pra_embedding_index
        FOR $query_embedding
        LIMIT $top_k
    ) SCORE AS score
    RETURN coalesce(node.uri, 'neo4j://node/' + coalesce(node.name, toString(elementId(node)))) AS uri,
           coalesce(node.label, node.name) AS label,
           node.description AS description,
           node.comment AS comment,
           labels(node) AS node_labels,
           score
    ORDER BY score DESC
    """

    def __init__(self, client: Any, embedding_client: Any | None = None) -> None:
        self._client = client
        self._settings = get_settings()
        self._embedding_client = embedding_client
        self._fallback_factory: Callable[[], Any] | None = None
        self._fallback_service: Any | None = None

    def set_fallback_factory(self, factory: Callable[[], Any]) -> None:
        """Configure a lazy fallback without building it during normal startup."""
        self._fallback_factory = factory

    async def retrieve(self, question: str, max_results: int = 10) -> SimilarityEvidence:
        """Embed a question and return Neo4j vector results as SimilarityEvidence."""
        if not self._settings.embedding_enabled:
            return SimilarityEvidence(
                hits=[],
                note=(
                    "Similarity search is disabled. Set EMBEDDING_ENABLED=true and "
                    "provide an OpenAI or Azure OpenAI key to activate it."
                ),
            )

        try:
            top_k = int(max_results)
            if top_k <= 0:
                return SimilarityEvidence(hits=[], note="No vector results requested.")

            embedding_client, model = self._get_embedding_client()
            response = await embedding_client.embeddings.create(
                input=[question],
                model=model,
            )
            query_embedding = response.data[0].embedding
            rows = await self._client.execute_read_query(
                self.VECTOR_QUERY,
                query_embedding=query_embedding,
                top_k=top_k,
            )
            hits = [self._to_hit(row) for row in rows]
            hits.sort(key=lambda hit: hit.score, reverse=True)
            logger.info(
                "similarity_retrieve_neo4j",
                hits=len(hits),
                top_score=hits[0].score if hits else None,
                question=question,
            )
            evidence = SimilarityEvidence(
                mode="similarity",
                hits=hits,
                note="" if hits else "Neo4j vector index returned no results.",
            )
            return evidence
        except Exception as exc:
            logger.error("similarity_retrieve_neo4j_failed", error=str(exc))
            if self._fallback_factory is not None:
                try:
                    if self._fallback_service is None:
                        self._fallback_service = self._fallback_factory()
                    logger.warning(
                        "similarity_backend_fallback",
                        primary="neo4j_vector_index",
                        fallback="in_memory_numpy",
                        reason=str(exc),
                    )
                    return await self._fallback_service.retrieve(question, max_results)
                except Exception as fallback_exc:
                    logger.error(
                        "similarity_fallback_failed",
                        error=str(fallback_exc),
                    )
            return SimilarityEvidence(hits=[], note="Neo4j vector retrieval failed.")

    def _get_embedding_client(self) -> tuple[Any, str]:
        if self._embedding_client is not None:
            return self._embedding_client, self._settings.embedding_model

        settings = self._settings
        if settings.azure_openai_endpoint and settings.azure_openai_api_key:
            model = settings.azure_openai_embedding_deployment or settings.embedding_model
            return (
                AsyncAzureOpenAI(
                    api_key=settings.azure_openai_api_key,
                    azure_endpoint=settings.azure_openai_endpoint,
                    api_version=settings.azure_openai_api_version,
                ),
                model,
            )

        if not settings.openai_api_key:
            raise RuntimeError("No OpenAI or Azure OpenAI embedding credentials are configured")

        return (
            AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            ),
            settings.embedding_model,
        )

    @classmethod
    def _to_hit(cls, row: dict[str, Any]) -> SimilarityHit:
        label = cls._flatten(row.get("label"))
        description = cls._flatten(row.get("description"))
        comment = cls._flatten(row.get("comment"))
        node_types = [
            value
            for value in cls._values(row.get("node_labels"))
            if value != "Resource" and not value.startswith("_")
        ]
        text = " ".join(
            part for part in (label, description, comment, " ".join(sorted(node_types))) if part
        )
        return SimilarityHit(
            uri=str(row.get("uri") or ""),
            label=label,
            score=cls._normalize_neo4j_vector_score(row.get("score", 0.0)),
            text=text,
        )

    @staticmethod
    def _normalize_neo4j_vector_score(raw_score: Any) -> float:
        """Convert Neo4j's [0, 1] cosine score to PRA's raw cosine score.

        The legacy NumPy implementation exposes the cosine dot product after
        vector normalization. Neo4j reports cosine similarity on a [0, 1]
        scale, so the inverse mapping preserves the existing PRA score
        contract without clamping or otherwise changing score ordering.
        """
        return (2.0 * float(raw_score)) - 1.0

    @staticmethod
    def _values(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            values: list[str] = []
            for item in value:
                values.extend(Neo4jVectorRetrievalService._values(item))
            return values
        text = str(value).strip()
        return [text] if text else []

    @classmethod
    def _flatten(cls, value: Any) -> str:
        return "; ".join(cls._values(value))
