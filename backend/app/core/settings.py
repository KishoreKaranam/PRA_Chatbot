"""Application settings loaded from environment / .env file."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GraphDB
    graphdb_base_url: str = "http://localhost:7200"
    graphdb_repository: str = "Payment_Reference_Architecture"
    graphdb_username: str = ""
    graphdb_password: str = ""

    # LLM – standard OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"

    # LLM – Azure OpenAI (takes priority when endpoint is set)
    azure_openai_endpoint: str = ""          # e.g. https://MY-RESOURCE.openai.azure.com
    azure_openai_api_version: str = "2025-01-01-preview"
    azure_openai_deployment: str = ""        # deployment name (= model alias in Azure)
    azure_openai_embedding_deployment: str = ""  # embedding deployment name in Azure

    # Embeddings
    embedding_model: str = "text-embedding-3-large"
    embedding_enabled: bool = False

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


@lru_cache()
def get_settings() -> Settings:
    return Settings()
