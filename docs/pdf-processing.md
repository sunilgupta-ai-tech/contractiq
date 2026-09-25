# PDF processing (Phase 4)

Turns an uploaded PDF into a structured `ParsedDocument`: text blocks with positions, tables, images, and a label for every block (heading, paragraph, list item, header/footer, table text). Runs in the worker, never in the API.

## Flow

```text
upload (API) ──► queue ──► worker process_document
                            │
                            ├─ parse  (status PROCESSING)
                            │    PyMuPDF  : open, encryption check, text blocks + fonts, images
                            │               scanned-page detection
                            │    pdfplumber: ruled tables (text-layer pages only)
                            │    images   : save meaningful images as PNG
                            │
                            ├─ ocr    (status OCR_PROCESSING)
                            │    Tesseract: text for scanned pages (300 DPI render)
                            │    layout   : headings / lists / headers / footers / table text
                            │    save     : parsed.json next to the original PDF
                            │
                            └─ chunk → embed → index   (Phases 5–6)
```

Stored per version, under `tenants/{tenant}/documents/{document}/{version}/`:

| File | Contents |
|---|---|
| `original.pdf` | the upload |
| `parsed.json` | `ParsedDocument.to_dict()` — input for Phase 5 chunking |
| `images/page-{n}-{i}.png` | embedded images ≥150 px, for Phase 9 multimodal |

Written to the `document_versions` row: `page_count`, `is_scanned`, and `extraction_metadata` (pages, scanned pages, table/image counts, mean OCR confidence, warnings, engine versions, `parsed_key`).

## Code map

| Module | Responsibility |
|---|---|
| `app/document_processing/parser.py` | `ParsedDocument` data model; permanent errors (`EncryptedPdfError`, `CorruptPdfError`, `TooManyPagesError`) |
| `app/document_processing/pymupdf_parser.py` | open PDF, text blocks, images, scanned-page rule |
| `app/document_processing/pdfplumber_parser.py` | table extraction |
| `app/document_processing/tables.py` | table cell cleanup, markdown |
| `app/document_processing/images.py` | which images to keep; PNG export |
| `app/document_processing/ocr.py` | Tesseract call; words → paragraphs in PDF coordinates |
| `app/document_processing/layout.py` | block classification rules |
| `app/services/pdf_service.py` | orchestrates parsing; options; extraction summary |
| `app/services/ocr_service.py` | OCR of scanned pages; error policy |
| `workers/app/services/pipeline.py` | `parse` and `ocr` stage handlers |

## Key rules

* **Scanned page** = fewer than 25 text characters *and* images cover ≥50% of the page. Blank pages and "searchable scans" (which already have an OCR text layer) are not scanned.
* **Heading** = short (≤120 chars, ≤15 words), not ending like a sentence, and larger font / bold / all caps / a title-cased numbered or named heading ("8.3 Notice Period", "ARTICLE 5"). A numbered sentence ("8.3 The Supplier shall…") is body text.
* **Header/footer** = text in the top/bottom 8% of the page repeated on ≥50% of pages (digits ignored, so "Page 3 of 40" matches "Page 4 of 40"), or a bare page number.

## Failures

| Situation | Result |
|---|---|
| Password-protected (user password), corrupt, or more than `MAX_PDF_PAGES` | Version FAILED with a user-facing message; **not retried** |
| Owner-password-only PDF (printing/copying restricted) | Processed normally |
| One image undecodable, tables unreadable, OCR timeout on a page | Warning in `extraction_metadata.warnings`; document still processed |
| Tesseract binary or language pack missing | Job fails and is retried — a deployment problem, surfaced loudly |
| Storage/DB errors | Job fails and is retried (arq, up to 3 tries) |

## Configuration

`MAX_PDF_PAGES` (2000), `OCR_ENABLED` (true), `OCR_LANGUAGES` ("eng"; e.g. "eng+deu" with `tesseract-ocr-deu` added to `workers/Dockerfile`), `OCR_DPI` (300), `OCR_PAGE_TIMEOUT_S` (120), `MAX_IMAGES_PER_DOCUMENT` (200), `MIN_IMAGE_DIMENSION_PX` (150).

## Decisions

* **Unstructured is not used** — several GB of ML dependencies for little gain on typical contracts. See `app/document_processing/unstructured_parser.py` for when to revisit.
* **Licensing** — PyMuPDF is AGPL-3.0. Closed-source commercial distribution needs an Artifex commercial licence.
* **Reading order** is PyMuPDF's top-to-bottom, left-to-right sort, correct for single-column contracts. Multi-column layouts are a known limitation (revisit with evaluation data, Phase 12).
