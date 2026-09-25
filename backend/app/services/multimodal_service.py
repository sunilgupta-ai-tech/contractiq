"""
Multimodal enrichment of a parsed document (Phase 9): caption images and
summarise tables, in place, before chunking.

Enrichment, never a gate
------------------------
The document's text is already extracted; captions only make figures and
tables easier to find. So nothing here fails a document:

  * one image or table the model cannot handle  -> counted, skipped
  * the model cannot be used at all (no API key,
    unknown model, vision model not pulled)      -> all captioning skipped,
                                                    reason recorded as a warning
  * MULTIMODAL_ENABLED=false                     -> nothing runs

The outcome is written to extraction_metadata["multimodal"], so a document
indexed without captions is visible, and can be re-processed later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.logging import get_logger
from app.document_processing.parser import ParsedDocument
from app.llm.base import LLMConfigError, LLMProvider
from app.multimodal.image_processor import ImageProcessor
from app.multimodal.table_processor import TableProcessor
from app.multimodal.vision import MultimodalStats, VisionService
from app.storage import ObjectStorage

logger = get_logger(__name__)


@dataclass
class EnrichmentResult:
    stats: MultimodalStats
    warnings: list[str] = field(default_factory=list)


async def enrich_document(
    doc: ParsedDocument,
    *,
    tenant_id: str,
    settings: Settings,
    provider_factory: Callable[[], LLMProvider],
    storage: ObjectStorage,
    redis: Redis | None,
) -> EnrichmentResult:
    """Caption images and summarise tables in `doc` (mutated in place).

    `provider_factory` is called only when there is something to describe,
    so a document without images or tables never needs a vision model.
    """
    stats = MultimodalStats()
    has_images = any(page.images for page in doc.pages)
    has_tables = settings.table_summaries_enabled and any(page.tables for page in doc.pages)
    if not settings.multimodal_enabled or not (has_images or has_tables):
        return EnrichmentResult(stats)

    try:
        service = VisionService(provider_factory(), settings, redis, stats=stats)
        if has_images:
            await ImageProcessor(service, storage).caption_document(doc, tenant_id=tenant_id)
        if has_tables:
            tables = TableProcessor(service, max_tables=settings.max_table_summaries_per_document)
            await tables.summarise_document(doc, tenant_id=tenant_id)
    except LLMConfigError as exc:
        logger.warning("multimodal_unavailable", extra={"error": str(exc)})
        return EnrichmentResult(stats, [f"Images and tables were not described: {exc}"])
    return EnrichmentResult(stats)
