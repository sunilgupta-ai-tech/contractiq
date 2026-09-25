# Chunking (Phase 5)

Splits each parsed contract into **child** chunks (searched) and **parent** chunks (read by the LLM), following the contract's own outline instead of fixed-size windows.

## Flow

```text
parsed.json (Phase 4)
   │
   ├─ structure.build_segments   outline from headings + numbering → segments
   ├─ merge                      tiny segments join their neighbour (same section only)
   ├─ splitter.split_pieces      long segments → windows: paragraph > sentence > word
   ├─ children                   ≈ one clause each; tables = own TABLE chunks (markdown)
   ├─ parents                    one per section (split if > parent limit)
   │
   └─ chunks.json  (+ version.chunk_count)  →  embeddings (Phase 6)
```

Worker stage: `chunk` (status `CHUNKING`) in `workers/app/services/pipeline.py`. Output: `tenants/{t}/documents/{d}/{v}/chunks.json`.

## Code map

| Module | Responsibility |
|---|---|
| `app/chunking/models.py` | `Chunk`, levels, types, deterministic `chunk_id` |
| `app/chunking/structure.py` | heading/number parsing, outline stack, segments |
| `app/chunking/splitter.py` | sentence splitting (legal abbreviations), packing, overlap |
| `app/chunking/tokens.py` | conservative token estimate (~4 chars/token) |
| `app/services/chunking_service.py` | merge, children, tables, parents, linking |

## Outline rules

| Text | Level | Becomes |
|---|---|---|
| `8. TERMINATION`, `ARTICLE 8`, `Schedule 2`, unnumbered ALL-CAPS heading | 1 | section |
| `8.3 Notice Period`, `Section 8.3`, unnumbered heading inside a section | 2 | clause |
| `8.3.1 …` | 3 | sub-clause |
| Paragraph starting `8.3 The Supplier shall…` (dotted number) | 2+ | new clause |
| First unnumbered heading on page 1 before any content | — | document title |
| Content before the first section | — | "Preamble" |

A bare number (`8 weeks after…`) never starts a clause — it is usually a quantity.

## Chunk fields

`text` (shown and quoted), `embedding_text` (heading path + text, what Phase 6 embeds), `section`/`section_title`, `clause`/`clause_title`, `clauses` (all clause numbers in a merged chunk), `heading_path`, `page_start`/`page_end`, `regions` (page + bbox of each source block, for citation highlighting), `parent_id`, `token_count`.

IDs are UUIDv5 of `(version_id, level, ordinal)`: re-processing a version yields the same IDs, so Phase 6 upserts replace points rather than duplicating them.

## Settings

| Env var | Default | Meaning |
|---|---|---|
| `CHUNK_MAX_TOKENS` | 400 | child chunk ceiling |
| `CHUNK_MIN_TOKENS` | 60 | smaller segments merge with a neighbour |
| `CHUNK_OVERLAP_TOKENS` | 50 | overlap between pieces of one long clause |
| `CHUNK_PARENT_MAX_TOKENS` | 1600 | parent (section) ceiling |

Tokens are estimated, conservatively, so real chunks are never larger than the limit for any embedding model. `CHUNKER_VERSION` in `chunking_service.py` is stored in `chunks.json` and `extraction_metadata`; bump it when rules change so stale chunk sets can be found and re-chunked (the chunk stage can run from `parsed.json` alone — no OCR repeat).

## Known limits

* Split clauses cite whole source blocks (block-level, not character-level, highlighting).
* Clause numbering styles outside the table above (e.g. `(1)` top-level clauses, `1.a`) are treated as body text inside the current clause.
* A merged chunk records its first clause as `clause`; all merged clause numbers are in `clauses`.
