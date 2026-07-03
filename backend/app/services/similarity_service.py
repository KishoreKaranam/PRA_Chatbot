"""
Similarity / vector search service for the PRA knowledge graph.

╔══════════════════════════════════════════════════════════════════════════╗
║  ASSUMPTIONS & DESIGN                                                    ║
║                                                                          ║
║  GraphDB does NOT natively support vector/semantic similarity search     ║
║  (embeddings) as of GraphDB 10.x.  Native vector search may be added     ║
║  in future releases or via Ontotext's enterprise plugins.                ║
║                                                                          ║
║  This service implements an ADAPTER LAYER that:                          ║
║  1. Fetches all PRA entity labels + descriptions from GraphDB once       ║
║     (cached in memory on startup).                                       ║
║  2. Computes embeddings using OpenAI text-embedding-3-small (or any      ║
║     OpenAI-compatible endpoint) via the openai SDK.                      ║
║  3. Stores embeddings in a NumPy matrix and performs cosine similarity   ║
║     at query time.                                                       ║
║                                                                          ║
║  This approach is suitable for <50 k entities. For larger graphs,        ║
║  replace the NumPy store with a proper vector DB (Qdrant, Weaviate,      ║
║  Chroma, pgvector) without changing the public API of this service.      ║
║                                                                          ║
║  When embedding_enabled=false (default), this service returns an empty   ║
║  SimilarityEvidence with an explanatory note.                            ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import numpy as np
from openai import AsyncOpenAI, AsyncAzureOpenAI

from app.graphdb.client import GraphDBClient
from app.models.schemas import SimilarityEvidence, SimilarityHit
from app.core.settings import get_settings
from app.core.log_config import get_logger

logger = get_logger(__name__)


class SimilarityRetrievalService:
    """
    Adapter-pattern vector search over PRA entities.

    Swap _EmbeddingBackend to plug in a different vector store.
    """

    def __init__(self, client: GraphDBClient) -> None:
        self._db = client
        self._settings = get_settings()
        self._backend: _NumPyBackend | None = None
        self._ready = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def retrieve(
        self, question: str, max_results: int = 10
    ) -> SimilarityEvidence:
        if not self._settings.embedding_enabled:
            return SimilarityEvidence(
                hits=[],
                note=(
                    "Similarity search is disabled. "
                    "Set EMBEDDING_ENABLED=true and provide OPENAI_API_KEY to activate."
                ),
            )

        if not self._ready:
            await self._build_index()

        if self._backend is None or len(self._backend) == 0:
            return SimilarityEvidence(
                hits=[], note="Embedding index is empty."
            )

        hits = await self._backend.search(question, max_results)
        logger.info("similarity_retrieve", hits=len(hits), question=question[:80])
        return SimilarityEvidence(hits=hits)

    # ── Index builder ─────────────────────────────────────────────────────────

    async def _build_index(self) -> None:
        """Fetch all PRA entities and build an in-memory embedding index."""
        logger.info("similarity_index_building")
        sparql = """\
SELECT ?entity ?label ?desc WHERE {
  ?entity a ?cls .
  FILTER(STRSTARTS(STR(?cls), "https://example.org/pra#"))
  OPTIONAL { ?entity rdfs:label ?label }
  OPTIONAL { ?entity dcterms:description ?desc }
}
"""
        bindings = await self._db.select(sparql)
        records: list[dict] = []
        for b in bindings:
            uri = b.get("entity", {}).get("value", "")
            label = b.get("label", {}).get("value", "")
            desc = b.get("desc", {}).get("value", "")
            text = f"{label}. {desc}".strip(". ")
            if text:
                records.append({"uri": uri, "label": label, "text": text})

        if not records:
            logger.warning("similarity_index_empty")
            self._ready = True
            return

        # Build the right OpenAI client (Azure or standard)
        s = self._settings
        if s.azure_openai_endpoint and s.azure_openai_api_key:
            openai_client = AsyncAzureOpenAI(
                api_key=s.azure_openai_api_key,
                azure_endpoint=s.azure_openai_endpoint,
                api_version=s.azure_openai_api_version,
            )
            embed_model = s.azure_openai_embedding_deployment or s.embedding_model
            logger.info("embedding_backend", backend="azure", deployment=embed_model)
        else:
            openai_client = AsyncOpenAI(
                api_key=s.openai_api_key,
                base_url=s.openai_base_url,
            )
            embed_model = s.embedding_model
            logger.info("embedding_backend", backend="openai", model=embed_model)

        self._backend = await _NumPyBackend.build(
            records, openai_client, embed_model
        )
        self._ready = True
        logger.info("similarity_index_built", count=len(records))


# ── NumPy embedding backend ───────────────────────────────────────────────────

class _NumPyBackend:
    """
    Cosine-similarity search over a pre-computed NumPy embedding matrix.

    To replace with Qdrant / Weaviate / Chroma:
      - Implement the same `build` + `search` interface.
      - Swap this class in SimilarityRetrievalService._build_index.
    """

    def __init__(
        self,
        records: list[dict],
        matrix: np.ndarray,
        openai_client: AsyncOpenAI,
        model: str,
    ) -> None:
        self._records = records
        self._matrix = matrix           # shape: (N, D)
        self._openai = openai_client
        self._model = model

    def __len__(self) -> int:
        return len(self._records)

    @classmethod
    async def build(
        cls,
        records: list[dict],
        openai_client: AsyncOpenAI,
        model: str,
    ) -> "_NumPyBackend":
        texts = [r["text"] for r in records]
        # Batch embeddings (OpenAI accepts up to 2048 per request)
        embeddings: list[list[float]] = []
        batch_size = 256
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await openai_client.embeddings.create(input=batch, model=model)
            embeddings.extend([d.embedding for d in resp.data])

        matrix = np.array(embeddings, dtype=np.float32)
        # L2-normalise for cosine similarity via dot product
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        matrix /= norms
        return cls(records, matrix, openai_client, model)

    async def search(self, query: str, k: int) -> list[SimilarityHit]:
        resp = await self._openai.embeddings.create(input=[query], model=self._model)
        q_vec = np.array(resp.data[0].embedding, dtype=np.float32)
        q_vec /= max(np.linalg.norm(q_vec), 1e-9)

        scores = self._matrix @ q_vec          # cosine similarities
        top_idx = np.argsort(-scores)[:k]

        return [
            SimilarityHit(
                uri=self._records[i]["uri"],
                label=self._records[i]["label"],
                score=float(scores[i]),
                text=self._records[i]["text"][:300],
            )
            for i in top_idx
        ]
