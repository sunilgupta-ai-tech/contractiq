# Contract analysis (Phase 10)

Clause extraction, executive summaries, risk analysis, comparison and portfolio summaries. They all build on one step: **extracting a fixed set of standard clauses from each contract version, as cited, typed facts.**

```text
version ──► ClauseAgent (per topic: search → rerank → model → JSON → verify)
               │
               ▼
         clauses.json (cached per version)
               │
   ┌───────────┼──────────────┬───────────────┬──────────────────┐
   ▼           ▼              ▼               ▼                  ▼
extract-   summarize      risk-analysis    compare         portfolio-summary
clauses    (1 model call) (rules, no model) (align, no model) (aggregate, no model)
```

Only extraction and the summary narrative call the model. Risk flags, comparison notes, key terms and key dates are computed from the extracted facts, so they are deterministic, explainable and consistent with the quotes shown beside them.

## Clause extraction

Topics are defined in `app/agents/clause_topics.py`:

| Topic | Typed facts |
|---|---|
| parties | `parties` (list) |
| term | `effective_date`, `expiry_date` (dates), `initial_term_months` |
| auto_renewal | `auto_renews`, `renewal_term_months`, `non_renewal_notice_days` |
| termination_convenience | `permitted`, `notice_days`, `party` |
| termination_cause | `cure_days` |
| liability_cap | `capped`, `cap` |
| indemnity | `indemnifying_party`, `uncapped` |
| payment_terms | `payment_days` |
| price_change | `unilateral`, `notice_days`, `has_ceiling` |
| confidentiality | `duration_years` |
| data_protection | `subprocessor_objection_right` |
| assignment | `consent_required` |
| governing_law | `law` |
| dispute_resolution | `mechanism` |
| force_majeure | — |

For each topic (`app/agents/clause_agent.py`):

1. **Retrieve.** Hybrid search with the topic's contract-vocabulary query, limited to the one version and tenant-filtered. Image captions are excluded because they are not contract wording.
2. **Rerank.** Keep the best `ANALYSIS_EVIDENCE_PER_TOPIC` (4) chunks.
3. **Extract.** One model call, with the excerpts wrapped in nonce-tagged untrusted-content delimiters. It returns strict JSON: `found`, `excerpt` (cite number), `quote`, `summary`, `attributes`.
4. **Verify.** The cite number must exist. The quote must appear word for word in that excerpt (case, whitespace and curly quotes are ignored), which gives `verified=true`. Otherwise the excerpt's own text becomes the quote and `verified=false`. Attributes are coerced to their declared types, and a malformed value becomes `null`, so rules never run on garbage.

When no evidence is found, `found=false` and the model is not called. An unparseable reply or a failed call gives `error=true` for that topic only. It is never reported as "missing", and the analysis is not cached, so the next request retries it.

## Risk rules

`app/agents/risk_agent.py`. Rules are explicit code over extracted facts. They are not the model's opinion.

| Rule | Severity | Trigger |
|---|---|---|
| `no_liability_cap` | high | liability-cap topic searched, not found |
| `uncapped_liability` | high | `capped = false` |
| `uncapped_indemnity` | high | `uncapped = true` |
| `automatic_renewal` | medium | `auto_renews = true` (rationale names the notice period) |
| `long_termination_notice` | medium | `notice_days > RISK_MAX_NOTICE_DAYS` (60) |
| `unilateral_price_change` | medium | `unilateral = true` and no ceiling |
| `no_subprocessor_objection` | medium | `subprocessor_objection_right = false` |
| `no_termination_for_convenience` | low | not permitted, or not found |
| `long_payment_terms` | low | `payment_days > RISK_MAX_PAYMENT_DAYS` (60) |
| `free_assignment` | low | `consent_required = false` |
| `no_confidentiality` | low | searched, not found |
| `foreign_governing_law` | low | `law` doesn't mention `RISK_HOME_JURISDICTION` (off when unset) |

Clause findings cite the clause (page, clause, verified excerpt, regions). "Missing" findings (`missing=true`) cite nothing, and are raised only when the topic was searched without error. Finding ids are deterministic per (version, rule), so a client can attach review state to them. Review status (`open`, `reviewing`, `accepted`) isn't stored yet, so every finding is `open`. All output carries a disclaimer: it is advisory, not legal advice.

## Comparison

`app/agents/comparison_agent.py` aligns clauses **by topic**, not by clause number, so a renumbered clause (8.3 → 9.2) still lines up, and two different contracts can be compared.

* `missing`: the topic is on one side only.
* `same`: facts are equal and wording is ≥ 97% similar (compared on the whole clause text, not the quote).
* `changed`: the note lists each changed fact (`Notice days: 30 → 90.`), or `Wording changed (82% similar).` when only the wording changed.
* `risk`: the worst right-hand-side finding on that topic, for rows that are not `same`.

## Summary

One model call over the found clauses (numbered evidence blocks). It returns an overview with `[n]` markers, which are verified and renumbered by the Phase 7 citation checker, plus obligations. Each obligation must cite a real block, or it is dropped. Key terms, key dates and risk counts are added without the model. The **non-renewal notice deadline** is computed as expiry date minus notice days. It is the date teams most often miss, and contracts rarely state it outright.

## Caching and background analysis

* `analysis/clauses.json` and `analysis/summary.json` are stored next to each version's `parsed.json`, under the tenant prefix, so deleting a document removes them. Each carries a fingerprint: extractor version, answer model and embedding model. Stale files are recomputed, never served. `refresh: true` forces recomputation.
* Risk analysis and portfolio summaries span many documents. They use cached analyses, compute up to `ANALYSIS_SYNC_DOCUMENTS` (3) missing ones inline, and queue the rest as the `analyze_version` worker job, reported in `pending_document_ids`. Jobs are de-duplicated per version per hour. Documents still processing are also reported as pending.

## Access and errors

`analysis:run` permission (Admin, Manager, Employee and any custom role that has it; not Viewer). Every id is resolved inside the caller's tenant: another organisation's id gives 404, a version still processing gives 409, and comparing a version with itself gives 422. Model or search misconfiguration gives 503 "not configured"; temporary failures give 503 "temporarily unavailable".

## Cost

Per version: about 15 extraction calls (one per topic, only when evidence exists) plus 1 summary call, each paid once per fingerprint. Comparison, risk and portfolio calls add no model calls once versions are analysed.

## Settings

`ANALYSIS_EVIDENCE_PER_TOPIC` (4), `ANALYSIS_CONCURRENCY` (4), `ANALYSIS_SYNC_DOCUMENTS` (3), `ANALYSIS_MAX_DOCUMENTS` (50), `RISK_MAX_NOTICE_DAYS` (60), `RISK_MAX_PAYMENT_DAYS` (60), `RISK_HOME_JURISDICTION` (unset). The model is `LLM_PROVIDER` / `GEMINI_MODEL` / `OLLAMA_MODEL`, the same one as Q&A.

## Not yet

* The frontend's Compare and Risk pages still use demo data. The API returns richer objects (e.g. `{rows, counts}` rather than a bare row list, snake_case fields), so wiring them needs a small adapter in `frontend/services/analysis-service.ts`.
* Finding review status and write-back of extracted dates to `documents.effective_date` / `expiry_date`.
* Routing `/query` questions such as "compare v1 and v2" to these agents (the Phase 8 supervisor still sends every intent to Q&A).
