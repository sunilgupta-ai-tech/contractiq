# Guardrails (Phase 11)

Controls around every model interaction. They are applied in code, and none of them depend on the model obeying a prompt.

```text
request ─► rate limit ─► clean input ─► retrieve ─► wrap evidence (untrusted) ─► model
                                                                                  │
response ◄─ grounding policy ◄─ groundedness check ◄─ citation check ◄─ sanitise ◄┘
                (agent runs: tool permission, tenant injection, argument limits, budget, timeout)
```

| Layer | Where | What it does |
|---|---|---|
| Rate limits | `guardrails/input_guardrails.py`, `core/dependencies.rate_limit` | Redis fixed windows per user (and per organisation for `/query`). Returns 429 + `Retry-After` |
| Login throttling | `dependencies.LoginThrottle`, `api/v1/auth.py` | Failed logins per (IP, email) and per IP. Only failures count; a success resets the pair |
| Input cleaning | `input_guardrails.clean_text` (on `QueryRequest.question`) | NFKC normalisation; removes zero-width, bidi-override and control characters used to hide instructions |
| Untrusted evidence | `guardrails/prompt_injection.py` (Phase 1) | Nonce-tagged delimiters the document can't forge, plus heuristic injection flags |
| Output sanitising | `guardrails/output_guardrails.py` (in `resolve_citations`) | Strips echoed delimiter/system tags, redacts secret-like tokens, caps length. Adds `output:*` flags |
| Citation check | `services/citation_service.py` (Phase 7) | Drops invented `[n]`, renumbers, resolves page/clause |
| Groundedness | `guardrails/evidence_validator.py` | Checks each sentence against the evidence it cites (numbers must match, key words must overlap). Reports `groundedness` and `unsupported_claims` |
| Grounding policy | `QueryService._apply_grounding_policy` | `flag` (default) or `enforce` |
| Tool limits | `guardrails/tool_guardrails.py`, `agents/tools/registry.py` | Per-tool argument checks (query ≤ 500 chars, limit ≤ 100, ≤ 50 ids, no unknown arguments), on top of Phase 8's permission, tenant injection, call budget, retry/step limits, timeout and duplicate-search skipping |

## Rate limits

| Kind | Default | Scope |
|---|---|---|
| `/query` | 20 / min | per user |
| `/query` | 200 / min | per organisation |
| `/contracts/*` | 10 / min | per user |
| `/documents/upload` | 30 / min | per user |
| failed logins | 10 / 15 min | per (IP, email) |
| failed logins | 100 / 15 min | per IP |

The limit check runs *after* the permission check, so refused requests don't use up anyone's allowance. Keys are tenant-prefixed (`ciq:<tenant>:rl:…`). Login keys are global and store a hash of the IP and email, never the address itself.

**Redis down: fail open.** A cache outage must not take down Q&A or sign-in, and each login attempt still costs a bcrypt check. The outage is logged (`rate_limit_unavailable`). Behind a load balancer, run uvicorn with `--proxy-headers` (trusting only the load balancer), or every user shares the balancer's IP for the per-IP login limit.

## Groundedness

For each sentence of the answer (connectives such as "In summary:" are skipped):

1. **Cited?** A factual sentence without a valid `[n]` is unsupported (`uncited`).
2. **Numbers.** Every number, amount, percentage and year must appear in the cited block's text or heading. The heading carries the clause number, pages and version. Thousands separators are ignored. Example: `number 90 not in evidence`.
3. **Overlap.** At least 30% of the sentence's content words must appear in the cited text (`low overlap (12%)`).

`groundedness` = supported sentences / checked sentences. It is `null` when no answer was generated.

| `GROUNDING_MODE` | Effect |
|---|---|
| `flag` (default) | Answer returned unchanged, with `groundedness` and `unsupported_claims`. Weak answers are logged (`answer_claims_unsupported`) |
| `enforce` | If score < `GROUNDING_MIN_SCORE` (0.5), or any number is missing from its evidence, the answer is replaced by a "couldn't verify" message with `insufficient_evidence=true`. The cited passages stay listed so the user can read them |

**Why `flag` is the default:** the check is lexical. It is fast, free and deterministic, and very good at catching wrong numbers. But it can doubt a heavy paraphrase, and silently withholding correct answers is also a failure. Use Phase 12's evaluation set to calibrate `GROUNDING_MIN_SCORE` before switching to `enforce`. For a legal team that prefers "no answer" to a wrong one, `enforce` is the recommended production setting.

## API changes

* 429 `RATE_LIMITED` with a `Retry-After` header and `details.retry_after_s`, on `/query`, `/contracts/*`, `/documents/upload` and `/auth/login`.
* `/query` responses gain `groundedness` (0–1 or null) and `unsupported_claims` (`[{sentence, reason}]`).
* Questions made only of invisible characters are rejected as empty (422).

## Settings

`GROUNDING_MODE` (flag), `GROUNDING_MIN_SCORE` (0.5), `RATE_LIMIT_ENABLED` (true), `RATE_LIMIT_QUERY_PER_MINUTE` (20), `RATE_LIMIT_QUERY_TENANT_PER_MINUTE` (200), `RATE_LIMIT_ANALYSIS_PER_MINUTE` (10), `RATE_LIMIT_UPLOAD_PER_MINUTE` (30), `LOGIN_MAX_FAILURES` (10), `LOGIN_MAX_FAILURES_PER_IP` (100), `LOGIN_WINDOW_S` (900).
