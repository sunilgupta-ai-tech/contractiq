"""
Application configuration.

All configuration comes from environment variables (12-factor). The same
image runs in development, staging and production; only the environment
differs. Locally the values come from `.env`; in AWS they are injected into
the ECS task from Secrets Manager / SSM Parameter Store.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class StorageBackend(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class LLMProviderName(StrEnum):
    OLLAMA = "ollama"
    GEMINI = "gemini"


_INSECURE_JWT_DEFAULT = "change-me-in-every-environment"


class Settings(BaseSettings):
    """Typed, validated settings.

    Secrets are `SecretStr` so they never appear in `repr()`, logs or
    tracebacks by accident.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Application ---
    app_env: Environment = Environment.DEVELOPMENT
    app_name: str = "ContractIQ"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    log_json: bool = False
    api_v1_prefix: str = "/api/v1"
    # NoDecode: accept the comma-separated form from env vars (see validator).
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    max_upload_size_mb: int = 50

    # --- PostgreSQL ---
    database_url: str = (
        "postgresql+asyncpg://contractiq:contractiq_dev_password@postgres:5432/contractiq"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- Qdrant ---
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "contract_chunks"
    # Must equal the collection's vector size. Changing it (or the embedding
    # model) requires re-embedding every document — see docs/embeddings.md.
    embedding_dimension: int = 768

    # --- Storage ---
    storage_backend: StorageBackend = StorageBackend.LOCAL
    local_storage_path: str = "/data/storage"
    aws_region: str | None = None
    aws_s3_bucket: str | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None

    # --- PDF processing (worker) ---
    # Hard ceiling checked before any page is read, so a pathological file
    # can't tie up a worker for hours.
    max_pdf_pages: int = 2000
    # OCR for scanned pages. Languages use Tesseract codes joined by "+"
    # ("eng", "eng+deu"); each needs its language pack in the worker image.
    ocr_enabled: bool = True
    ocr_languages: str = "eng"
    ocr_dpi: int = 300  # accuracy drops noticeably below ~250 on small print
    ocr_page_timeout_s: int = 120
    # Embedded images kept for multimodal RAG (Phase 9). Smaller images are
    # logos/icons and are skipped.
    max_images_per_document: int = 200
    min_image_dimension_px: int = 150

    # --- Chunking (worker, Phase 5) ---
    # Sizes are *estimated* tokens (~4 chars each; see app/chunking/tokens.py).
    chunk_max_tokens: int = 400  # child chunk: about one clause
    chunk_min_tokens: int = 60  # smaller segments merge with a neighbour
    chunk_overlap_tokens: int = 50  # carried between pieces of one long clause
    chunk_parent_max_tokens: int = 1600  # parent (section) context for the LLM

    # --- LLM (backend only; never sent to the browser) ---
    llm_provider: LLMProviderName = LLMProviderName.OLLAMA
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.1:8b"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.0-flash"

    # --- Embeddings (Phase 6) ---
    # Gemini by default (hosted; needs GEMINI_API_KEY). For fully local
    # development use EMBEDDING_PROVIDER=ollama, EMBEDDING_MODEL=nomic-embed-text.
    embedding_provider: LLMProviderName = LLMProviderName.GEMINI
    embedding_model: str = "gemini-embedding-001"
    # Texts per API call. Gemini's batchEmbedContents accepts up to 100.
    embedding_batch_size: int = 100
    # Retries for rate limits (429), server errors (5xx) and timeouts, with
    # exponential backoff. Bad keys / bad requests are never retried.
    embedding_max_retries: int = 5
    embedding_timeout_s: float = 60.0
    # Vectors cached in Redis by content hash (per tenant) so unchanged
    # clauses in a new contract version are not paid for twice. 0 disables.
    embedding_cache_ttl_s: int = 30 * 24 * 3600

    # --- Auth ---
    jwt_secret_key: SecretStr = SecretStr(_INSECURE_JWT_DEFAULT)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- Observability ---
    langsmith_api_key: SecretStr | None = None
    langsmith_tracing: bool = False
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        # Accept "a,b" from env vars as well as a JSON list.
        if isinstance(value, str):
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> Settings:
        """Refuse to boot a non-dev environment with unsafe settings.

        Failing at startup is far cheaper than discovering in an incident
        that production was signing JWTs with the example secret.
        """
        if self.app_env is Environment.DEVELOPMENT:
            return self
        if self.jwt_secret_key.get_secret_value() == _INSECURE_JWT_DEFAULT:
            raise ValueError("JWT_SECRET_KEY must be set outside development")
        if self.storage_backend is StorageBackend.S3 and not self.aws_s3_bucket:
            raise ValueError("AWS_S3_BUCKET is required when STORAGE_BACKEND=s3")
        if any(origin == "*" for origin in self.cors_origins):
            raise ValueError("Wildcard CORS origins are not allowed outside development")
        uses_gemini = LLMProviderName.GEMINI in (self.embedding_provider, self.llm_provider)
        if uses_gemini and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when a Gemini provider is selected")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, overridable in tests via dependency_overrides."""
    return Settings()
