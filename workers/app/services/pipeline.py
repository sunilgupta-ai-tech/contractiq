"""
Document ingestion pipeline definition.

The pipeline is an ordered list of stages. Each stage maps to a
`DocumentStatus`, so the status the user sees in the UI is exactly the
stage the worker is executing. Stage handlers are filled in phase by phase
(PDF + OCR in Phase 4, chunking in 5, embeddings + Qdrant in 6); until then
they are explicit pass-throughs so the orchestration, status tracking,
retries and failure handling are exercised end-to-end from Phase 1.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.db.models import DocumentStatus

StageHandler = Callable[["StageContext"], Awaitable[None]]


@dataclass
class StageContext:
    """Mutable state handed from stage to stage for one document version."""

    tenant_id: str
    document_id: str
    version_id: str
    storage_key: str
    resources: Any
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Stage:
    name: str
    status: DocumentStatus
    handler: StageHandler
    progress: int  # % complete once this stage finishes


async def _parse(ctx: StageContext) -> None:
    """Phase 4: PyMuPDF/PDFPlumber/Unstructured parsing -> ctx.artifacts['parsed']."""


async def _ocr(ctx: StageContext) -> None:
    """Phase 4: OCR only the pages detected as scanned."""


async def _chunk(ctx: StageContext) -> None:
    """Phase 5: section/clause-aware chunking with parent/child IDs."""


async def _embed(ctx: StageContext) -> None:
    """Phase 6: batch embeddings via EmbeddingProvider."""


async def _index(ctx: StageContext) -> None:
    """Phase 6: delete this version's old points, then upsert new ones.

    Delete-then-upsert keyed by version_id makes re-processing idempotent:
    a retried job can never leave duplicate chunks in Qdrant.
    """


PIPELINE: tuple[Stage, ...] = (
    Stage("parse", DocumentStatus.PROCESSING, _parse, 25),
    Stage("ocr", DocumentStatus.OCR_PROCESSING, _ocr, 45),
    Stage("chunk", DocumentStatus.CHUNKING, _chunk, 65),
    Stage("embed", DocumentStatus.EMBEDDING, _embed, 85),
    Stage("index", DocumentStatus.INDEXING, _index, 100),
)
