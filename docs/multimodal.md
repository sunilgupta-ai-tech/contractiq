# Multimodal (Phase 9)

Makes images and tables searchable. A vision model **captions** each image saved in Phase 4 (charts, diagrams, signatures, stamps), and **summarises** each table. Captions become their own cited chunks, and table summaries are embedded alongside the table text. Questions such as *"who signed for Acme?"*, *"what does the escalation diagram show?"* or *"when is the final payment due?"* can then find content that is not in the contract's text.

## Flow

```text
parse → ocr → describe → chunk → embed → index
                 │
                 ├─ ImageProcessor   PNG + prompt  → vision model → KIND + DESCRIPTION
                 │                   → PageImage.kind / .caption
                 ├─ TableProcessor   table markdown → same model   → 1–2 sentence summary
                 │                   → Table.summary
                 └─ parsed.json re-saved (so re-chunking never repeats model calls)
```

Worker stage: `describe` in `workers/app/services/pipeline.py`. It reports status `OCR_PROCESSING` (content extraction), so the database enum and the UI stepper are unchanged. Progress goes 45% → 55%.

## What gets indexed

| Source | Chunk | `text` (shown, quoted) | `embedding_text` (searched) | Citation region |
|---|---|---|---|---|
| Captioned image | own `IMAGE_CAPTION` child, in the clause where the image appears | `[Image: signature] Signed by Jane Doe, CFO …` | heading path + text | the image's bbox on its page |
| Table | `TABLE` child (as in Phase 5) | the exact markdown table | heading path + **summary** + table | the table's bbox |
| Logo / decoration | none | — | — | — |

* The caption is also part of its section's **parent** chunk, so small-to-big context (Phase 7) includes it.
* `media_key` on caption chunks (in `chunks.json` and the Qdrant payload) is the image's storage key, so a later UI can show the figure itself.
* Citations now carry `chunk_type` (`text` | `table` | `image_caption`). An `image_caption` quote is a model-written description of a figure, not contract wording, and the UI should present it that way.
* `CHUNKER_VERSION` is now 2. Documents without captions or summaries chunk exactly as before: same text, same ids, same embedding text, so embedding-cache hits are kept.

## Code map

| Module | Responsibility |
|---|---|
| `app/multimodal/vision.py` | `VisionService`: retries, tenant-scoped Redis cache, concurrency limit, stats |
| `app/multimodal/image_processor.py` | image prompt, `parse_caption`, decorative filtering |
| `app/multimodal/table_processor.py` | table prompt and summaries |
| `app/services/multimodal_service.py` | `enrich_document`: runs both, never fails a document |
| `app/llm/{gemini,ollama}.py` | `ChatMessage.images` sent as Gemini `inlineData` / Ollama `images` |
| `app/chunking/structure.py`, `app/services/chunking_service.py` | image segments → `IMAGE_CAPTION` chunks; summary in table embedding text |

## Failure policy: enrichment, never a gate

| Situation | Result |
|---|---|
| One image/table fails (retries exhausted, reply blocked, image file missing) | counted in `images_failed` / `tables_failed`; the rest continue |
| Model unusable (no key, unknown model, Ollama vision model not pulled) | all captioning skipped; reason added to `extraction_metadata.warnings`; document still indexed |
| `MULTIMODAL_ENABLED=false`, or nothing to describe | stage does nothing; no model is created |

Per-version outcome: `extraction_metadata.multimodal` = `model`, `images`, `images_captioned`, `images_decorative`, `images_failed`, `tables`, `tables_summarised`, `tables_failed`, `cache_hits`, `api_calls`, `retries`. To add captions to a document that was indexed without them, re-process it after fixing the configuration.

## Security

Images and tables are untrusted document content. The system prompt tells the model to describe text in an image but never follow instructions in it. Replies are length-capped (captions 1,200 characters, summaries 500), and captions then go through the same delimited, cited evidence path as all contract text (Phase 7). Cache keys are tenant-prefixed (`ciq:<tenant>:mm:…`), so one organisation's captions are never reused for another, even for identical images.

**Privacy:** with Gemini, images and table text are sent to Google. Check the data-processing terms of your Gemini API tier before processing client contracts, or use Ollama to keep everything local.

## Cost controls

* **Cache:** replies are cached by the hash of the exact input, the model and the prompt version (`img-v1`, `tbl-v1`). Unchanged figures in a new contract version cost nothing. When you change a prompt, bump its tag.
* **Limits:** at most `MAX_IMAGES_PER_DOCUMENT` images (200, Phase 4) and `MAX_TABLE_SUMMARIES_PER_DOCUMENT` tables (100). Images under `MIN_IMAGE_DIMENSION_PX` are never saved, and full-page scans are OCR'd, not captioned.
* **Concurrency:** `VISION_CONCURRENCY` calls in flight per document. Retries use exponential backoff with jitter, only for 408/429/5xx/network errors.

## Providers

**Gemini (default)** reuses `GEMINI_API_KEY`:

```env
VISION_PROVIDER=gemini
VISION_MODEL=gemini-2.5-flash
```

**Ollama (local)** needs a vision model pulled (`ollama pull qwen2.5vl:7b`, or `llava:7b`):

```env
VISION_PROVIDER=ollama
VISION_MODEL=qwen2.5vl:7b
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Outside `development`, the app refuses to start if `VISION_PROVIDER=gemini` (with `MULTIMODAL_ENABLED=true`) and there is no `GEMINI_API_KEY`.

## Settings

`MULTIMODAL_ENABLED` (true), `VISION_PROVIDER` (gemini), `VISION_MODEL` (gemini-2.5-flash), `VISION_TIMEOUT_S` (60), `VISION_CONCURRENCY` (4), `VISION_MAX_RETRIES` (3), `TABLE_SUMMARIES_ENABLED` (true), `MAX_TABLE_SUMMARIES_PER_DOCUMENT` (100), `CAPTION_CACHE_TTL_S` (30 days; 0 disables).
