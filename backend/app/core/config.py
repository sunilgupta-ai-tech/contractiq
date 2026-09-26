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
from typing import Annotated, Literal

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

    # --- Multimodal (worker, Phase 9) ---
    # Images are captioned and tables summarised by the vision model, so both
    # become searchable. Enrichment only: if the model is unavailable the
    # document is still indexed, without captions (and says so in metadata).
    multimodal_enabled: bool = True
    # Gemini by default. For local use: VISION_PROVIDER=ollama and a pulled
    # vision model, e.g. VISION_MODEL=qwen2.5vl:7b (or llava:7b).
    vision_provider: LLMProviderName = LLMProviderName.GEMINI
    vision_model: str = "gemini-2.5-flash"
    vision_timeout_s: float = 60.0
    vision_concurrency: int = 4  # model calls in flight per document
    vision_max_retries: int = 3  # for rate limits / 5xx / timeouts
    table_summaries_enabled: bool = True
    max_table_summaries_per_document: int = 100
    # Captions/summaries cached in Redis by content hash (per tenant), so a
    # new version with the same figures costs nothing. 0 disables.
    caption_cache_ttl_s: int = 30 * 24 * 3600

    # --- Chunking (worker, Phase 5) ---
    # Sizes are *estimated* tokens (~4 chars each; see app/chunking/tokens.py).
    chunk_max_tokens: int = 400  # child chunk: about one clause
    chunk_min_tokens: int = 60  # smaller segments merge with a neighbour
    chunk_overlap_tokens: int = 50  # carried between pieces of one long clause
    chunk_parent_max_tokens: int = 1600  # parent (section) context for the LLM

    # --- LLM (backend only; never sent to the browser) ---
    # Answer generation. Gemini by default; LLM_PROVIDER=ollama runs locally.
    # Model names change over time — check Google's current model list
    # before production and set GEMINI_MODEL explicitly.
    llm_provider: LLMProviderName = LLMProviderName.GEMINI
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.1:8b"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Gemini 2.5 "thinking" budget in tokens; unset = model default. 0 turns it
    # off on 2.5 Flash: cheaper, faster, and short JSON replies aren't cut off.
    gemini_thinking_budget: int | None = None
    llm_timeout_s: float = 60.0
    llm_max_output_tokens: int = 1024

    # --- Retrieval & answering (Phase 7) ---
    # Candidates fetched by each search (dense and keyword) before fusion.
    retrieval_prefetch: int = 40
    # Candidates kept after fusion, handed to the reranker.
    retrieval_candidates: int = 20
    # Evidence chunks kept after reranking, i.e. what the answer may cite.
    rerank_top_n: int = 6
    reranker: str = "heuristic"  # heuristic | none
    # Estimated-token budget for all evidence in the prompt (sections included).
    context_max_tokens: int = 6000
    # Previous question/answer pairs included for follow-up questions.
    conversation_history_turns: int = 3

    # --- Guardrails (Phase 11) ---
    # Groundedness: "flag" returns the score and unsupported sentences with the
    # answer; "enforce" withholds answers scoring below GROUNDING_MIN_SCORE or
    # stating a number their evidence doesn't contain. See
    # app/guardrails/evidence_validator.py before switching to enforce.
    grounding_mode: Literal["flag", "enforce"] = "flag"
    grounding_min_score: float = 0.5
    # Rate limits (Redis, fixed windows). Fail open if Redis is down.
    rate_limit_enabled: bool = True
    rate_limit_query_per_minute: int = 20  # per user
    rate_limit_query_tenant_per_minute: int = 200  # per organization
    rate_limit_analysis_per_minute: int = 10  # per user, /contracts/*
    rate_limit_upload_per_minute: int = 30  # per user
    # Failed logins per (IP, email) and per IP, in LOGIN_WINDOW_S. Behind a
    # load balancer, run uvicorn with --proxy-headers so the IP is the client's.
    login_max_failures: int = 10
    login_max_failures_per_ip: int = 100
    login_window_s: int = 15 * 60

    # --- Agent (Phase 8) ---
    # "agent" = LangGraph workflow (rewrite, decompose, retry); "fast" = the
    # single-pass Phase 7 pipeline. A request can override it with `mode`.
    query_mode: str = "agent"
    agent_max_retries: int = 2  # refine-and-search-again rounds
    agent_max_sub_questions: int = 3
    agent_max_tool_calls: int = 12  # searches per question, across all retries
    agent_timeout_s: float = 90.0  # whole run, including every model call

    # --- Contract analysis (Phase 10) ---
    # Clause extraction: for each standard topic, the best N chunks of the
    # version are shown to the answer model (LLM_PROVIDER). Results are
    # cached per version in storage (analysis/clauses.json).
    analysis_evidence_per_topic: int = 4
    analysis_concurrency: int = 4  # topic extractions in flight per document
    # Multi-document requests (risk analysis, portfolio) analyse at most this
    # many not-yet-analysed documents inline; the rest are queued for the
    # worker and reported as pending.
    analysis_sync_documents: int = 3
    analysis_max_documents: int = 50  # documents per portfolio/risk request
    # Risk-rule thresholds (policy, not model behaviour). Advisory only.
    risk_max_notice_days: int = 60
    risk_max_payment_days: int = 60
    # e.g. "India"; unset disables the foreign-governing-law rule.
    risk_home_jurisdiction: str | None = None

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
    # Prometheus metrics at GET /metrics (and WORKER_METRICS_PORT on the worker,
    # 0 = off). If METRICS_TOKEN is set, scrapes must send it as a bearer token.
    metrics_enabled: bool = True
    metrics_token: SecretStr | None = None
    worker_metrics_port: int = 9101
    # USD per million tokens by model name, for cost metrics; e.g.
    # {"gemini-2.5-flash": {"input_per_mtok": 0.30, "output_per_mtok": 2.50}}.
    # No built-in prices: take them from the provider's current price list.
    llm_pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    # Per-question traces: auto (Langfuse if keys are set) | langfuse | log | none.
    tracing: Literal["auto", "langfuse", "log", "none"] = "auto"
    # Send question/answer text to the tracing backend (off: ids/timings only).
    langfuse_capture_content: bool = False
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
        providers = [self.embedding_provider, self.llm_provider]
        if self.multimodal_enabled:
            providers.append(self.vision_provider)
        uses_gemini = LLMProviderName.GEMINI in providers
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
