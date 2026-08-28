"""Application settings loaded from environment / .env file."""
from functools import lru_cache
from pathlib import Path
from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file's directory (backend/)
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Retrieval backend: "neo4j" (Cypher) — primary backend
    retrieval_backend: str = "neo4j"

    # FTS backend: "neo4j" uses Neo4j CONTAINS search
    fts_backend: str = "neo4j"

    # Graph backend: "neo4j"
    graph_backend: str = "neo4j"

    # Neo4j connection settings
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # LLM Provider: "openai" | "azure" | "anthropic"
    llm_provider: str = "anthropic"

    # LLM – standard OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"

    # LLM – Azure OpenAI (used when llm_provider=azure)
    azure_openai_api_key: str = ""           # separate key for Azure OpenAI
    azure_openai_endpoint: str = ""          # e.g. https://MY-RESOURCE.openai.azure.com
    azure_openai_api_version: str = "2025-01-01-preview"
    azure_openai_deployment: str = ""        # deployment name (= model alias in Azure)
    azure_openai_embedding_deployment: str = ""  # embedding deployment name in Azure

    # LLM – Anthropic Claude (used when llm_provider=anthropic)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_max_tokens: int = 8096

    # Embeddings
    embedding_model: str = "text-embedding-3-large"
    embedding_enabled: bool = False
    vector_backend: str = "legacy"  # "legacy"=in-memory NumPy+Azure; "neo4j"=requires pra_embedding_index

    # App
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    log_level: str = "INFO"

    # Agent defaults
    default_retrieval_strategy: str = "hybrid"
    default_answer_style: str = "business"
    default_max_results: int = 10
    default_show_evidence: bool = True
    default_strict_ontology_mode: bool = False
    default_confidence_threshold: float = 0.3

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pra_chatbot"
    db_pool_size: int = 10
    db_max_overflow: int = 20


@lru_cache()
def get_settings() -> Settings:
    return Settings()
