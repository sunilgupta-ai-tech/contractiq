# Production scale (Phase 21)

How DocuNexa AI handles large files, many documents, bad scans, broken PDFs, model outages and cost.

## Large files

- **Uploads are streamed.** The API writes the upload to a temporary file in 1 MB pieces and computes the SHA-256 as it goes; the whole file is never in memory ([`spool_upload`](../backend/app/services/document_service.py)).
- **Validation reads the disk file.** Format checks work on the file on disk: the first bytes, a ZIP index, and an image header.
- **Stored from disk.** The file goes to storage with `put_file`. On S3, boto3 switches to multipart upload above 8 MB.
- **Size limit.** `MAX_UPLOAD_SIZE_MB` (default 50) is enforced while streaming, so a 2 GB request is stopped at the limit rather than after it arrives. Raise it for large documents, and raise the proxy or load balancer body limit to match.
- **Processing is never on the API.** It always happens in the worker. The worker holds one document's bytes while parsing, so give workers memory for the largest file you accept. `MAX_PDF_PAGES` stops pathological files early.

## Many documents

The following were already in place and remain the approach:
- **Queue:** every upload is a queued job (arq on Redis), and workers scale horizontally (`max_jobs` per worker, more replicas for throughput).
- **Library:** paging, filtering and counting run in SQL with per-tenant indexes (Phase 15).
- **Search:** vector search uses Qdrant's tenant-partitioned payload index.

## Bad scans: review status

After OCR and handwriting transcription, the worker decides whether a person should check the text. A document is flagged `needs_review` when any of these hold:
- `low_ocr_confidence`: scanned pages whose OCR stayed weak and could not be transcribed.
- `no_text_found`: scanned pages with no text at all.
- `damaged_pdf_recovered`: only the fallback reader could open the PDF.

The document is still indexed; the flag tells people to double-check answers from it. The library has a **Needs review** filter, and the document page shows the reasons and a **Mark reviewed** button (`POST /documents/{id}/reviewed`, audited). Temporary failures are retried by the queue (3 tries).

## Broken PDFs: fallback parsers

1. **A page whose text layer cannot be read** (broken fonts or content streams) no longer fails the document. It is treated as a scanned page and OCR'd, with a warning.
2. **A PDF that PyMuPDF cannot open** is read with pdfplumber (pdfminer), which tolerates some damaged cross-reference tables and encodings. The text keeps its positions; images and tables may be missing. The document is flagged for review.
3. **Only if both readers fail** is the file rejected as corrupt.

## Model rate limits and outages

Every answer and planning call goes through [`ResilientLLM`](../backend/app/llm/resilient.py):

| Setting | Default | Effect |
|---|---|---|
| `LLM_MAX_RETRIES` | 2 | 429 / 5xx / timeouts retried with exponential backoff and jitter |
| `LLM_FALLBACK_MODEL` | — | One call to this model after the retries (e.g. `gemini-2.5-flash-lite`) |
| `LLM_BREAKER_THRESHOLD` / `LLM_BREAKER_COOLDOWN_S` | 5 / 30 s | Circuit breaker: after N consecutive failures the primary is paused; requests go to the fallback, or fail fast with 503 instead of waiting for timeouts |

Configuration errors (bad key, unknown model) and safety blocks are never retried. Per-user and per-organization request limits (Phase 11) sit in front of all of this.

## Cost

- **Answer cache** (`ANSWER_CACHE_TTL_S`, default 6 h): a first question already answered is served from Redis with zero tokens. The key covers:
  - the organization;
  - the normalized question;
  - the mode and scope;
  - the documents this user cannot see;
  - the organization's corpus version, so any upload, processing, deletion or access change invalidates it;
  - the prompt version and model.

  Follow-up questions, "not found" answers and answers with injection flags are never cached. Hit rate: the `contractiq_answer_cache_total` metric.
- **Model routing** (`LLM_LIGHT_MODEL`): planning and query rewriting, which are short and frequent, go to a lighter model; answers keep `GEMINI_MODEL`.
- **Already in place:**
  - embedding, caption and analysis caches;
  - `GEMINI_THINKING_BUDGET=0`;
  - `LLM_MAX_OUTPUT_TOKENS`;
  - one table summary per spreadsheet sheet;
  - handwriting transcription only on weak pages.

## Search speed

The following are unchanged, and each is what keeps search fast with millions of chunks:
- **Qdrant filtering:** tenant is a partitioning payload index; document, version, current-version and level fields are indexed.
- **One-call hybrid search:** a single call fuses dense and keyword results, with the filter inside each candidate list.
- **Reranking:** a small candidate set is reranked.
- **Small-to-big context:** sections are fetched by id.
