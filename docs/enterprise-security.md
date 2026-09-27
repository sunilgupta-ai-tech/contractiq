# Enterprise security (Phase 24)

This page covers how DocuNexa AI handles encryption, secrets, malicious uploads, personal data and deletion. Access control, tenant isolation and prompt-injection defences are in [`security.md`](security.md). Model-output guardrails are in [`guardrails.md`](guardrails.md).

## Encryption

| Where | In transit | At rest |
|---|---|---|
| Browser ↔ API | HTTPS at the load balancer (TLS certificate) | — |
| API/worker ↔ PostgreSQL | `?ssl=require` in `DATABASE_URL`; set RDS `rds.force_ssl=1` | RDS storage encryption (KMS) |
| API/worker ↔ Redis | `rediss://` URL (ElastiCache in-transit encryption) | ElastiCache at-rest encryption |
| API/worker ↔ Qdrant | `https://` + `QDRANT_API_KEY` | Qdrant Cloud disk encryption |
| API/worker ↔ S3 | HTTPS (boto3 default); also deny plain HTTP with an `aws:SecureTransport` bucket policy | SSE-S3 (AES-256), or SSE-KMS with your key |
| Backups | — | RDS snapshots inherit encryption. `backups/` dumps: keep them on encrypted disk or storage |

Local Docker Compose uses plain connections on a private network. That is fine for development, and wrong for real contracts.

### Customer-managed KMS key (runbook)

Set `AWS_S3_KMS_KEY_ID` (key ARN or alias). Every object written from then on uses SSE-KMS with that key. Without it, objects use S3-managed AES-256.

1. Create a symmetric KMS key. Enable automatic yearly rotation.
2. Key policy: allow the API and worker task roles `kms:GenerateDataKey` and `kms:Decrypt`. Allow key administration only to your security admins.
3. Set `AWS_S3_KMS_KEY_ID`, and roll the API and worker.
4. Existing objects keep their old encryption. To re-encrypt them, copy each object onto itself, e.g. `aws s3 cp s3://<bucket>/tenants/ s3://<bucket>/tenants/ --recursive --sse aws:kms --sse-kms-key-id <key>`.
5. **Never schedule the key for deletion while objects use it**: they become unreadable. Disabling the key is the emergency brake: every read fails until it is re-enabled.

## Secrets

- Secrets come from the environment: `.env` locally (git-ignored), and Secrets Manager or SSM in production. They are `SecretStr` in code, so they never appear in logs or reprs (see `security.md`).
- **CI secret scan:** the `secrets` job in `.github/workflows/ci.yml` runs [gitleaks](https://github.com/gitleaks/gitleaks) over the **whole git history** on every push and pull request. The Docker build job waits for it. Run it locally with `make secret-scan`. At the time of Phase 24 the history (34 commits) was clean.
- **If a secret was committed:** deleting it in a new commit is not enough, because it stays in history. Rotate it at once, and only then clean the history if needed.
  - `GEMINI_API_KEY`: create a new key in Google AI Studio and delete the old one.
  - `JWT_SECRET_KEY`: set a new value. This signs everyone out.
  - Database password: change it on the server, then update `DATABASE_URL`.

## Malicious uploads

Every upload passes these layers before anything is stored:

1. **Size limit**, streamed to a temporary file, so a large upload never sits in memory (Phase 21).
2. **Content checks** (Phase 16): real file type from its bytes, not the file name. Legacy, macro-enabled and password-protected Office files are refused, and so are zip bombs.
3. **Duplicate check and plan limits** (Phases 19, 18).
4. **Malware scan** (Phase 24): the file is streamed to ClamAV (clamd `INSTREAM`).
   - An infected file is refused with `422 MALWARE_DETECTED`: "This file was flagged by the malware scanner and was not uploaded."
   - Nothing is stored or processed. An audit entry `document.upload_blocked` records the file name, hash and signature.
5. Processing then happens in the worker, as a non-root user, with page, image and cell limits.

Turn scanning on with `MALWARE_SCAN=clamav`. The scanner is `CLAMAV_HOST:CLAMAV_PORT` (default `clamav:3310`).

```bash
docker compose --profile security up -d clamav   # first start downloads signatures (~5 min, ~1 GB RAM)
# .env: MALWARE_SCAN=clamav
```

- **Fail closed.** If the scanner can't answer (down, timeout, or a file above its `StreamMaxLength`), the upload is refused with 503 "could not be checked for malware right now". `MALWARE_SCAN_ON_ERROR=allow` lets such files through with a log warning instead. Only use it if availability matters more to you than scanning every file.
- **Size.** Set clamd's `StreamMaxLength`, `MaxFileSize` and `MaxScanSize` at or above `MAX_UPLOAD_SIZE_MB`. The compose service sets them to 1100M.
- **Signatures.** The ClamAV container updates its signatures itself (freshclam).
- **Production.** Run ClamAV as its own ECS service (or sidecar) reachable only from the API's security group.
- **Metric:** `contractiq_malware_scans_total{outcome=clean|infected|error}`. Alert on any `infected`, and on a rising `error` rate.

## Personal data (PII)

After chunking, the worker counts the personal data in each version:

| Kind | Detected as |
|---|---|
| `aadhaar` | 12 digits (first 2–9), optionally 4-4-4, **valid Verhoeff check digit** |
| `pan` | PAN format with a valid holder-type letter (a GSTIN's embedded PAN is not counted) |
| `card` | 13–19 digits, known card prefix, **valid Luhn checksum** |
| `email` | e-mail address |
| `phone` | Indian mobile (+91 / 0, starting 6–9), or `+<country>` international number |

- Only the **number of distinct values per kind** is stored, in `extraction_metadata.pii`, never the values themselves.
- The API returns it as `pii` on each version, e.g. `{"aadhaar": 2, "email": 5}`. The document page shows "Contains personal data: 2 Aadhaar numbers, 5 email addresses".
- Documents processed before Phase 24 show nothing until they are processed again. Turn detection off with `PII_DETECTION_ENABLED=false`.

Protection of the data itself:
- **Access control:** restricted documents and grants (Phase 20). Use RESTRICTED for HR files, KYC documents and registers.
- **Encryption:** see above.
- **Audit trail:** uploads, downloads, deletions, questions and blocked uploads are recorded (Phase 22).
- **`PII_MASK_ANSWERS=true`** (off by default) masks Aadhaar and card numbers in Assistant answers and their quotes, both as shown and as stored in the conversation. Only the last 4 digits remain, e.g. `XXXX XXXX 2346` or `•••• 1111`. The document itself is not changed.

## Data deletion

Deleting a document removes it everywhere:

| Where | What | When |
|---|---|---|
| Qdrant | every vector of every version | first, synchronously. Nothing is retrievable once the delete returns |
| PostgreSQL | document, versions, jobs, grants (cascade) | same request |
| Conversations | answers that cited the document are replaced by "This answer was removed because a document it cited has been deleted." Their citations are cleared, and the document leaves conversation scopes. The users' questions stay | same transaction |
| Object storage | original files, `parsed.json`, `chunks.json`, images, analyses | same request, and again by the purge job |
| Redis | the organization's answer, caption/table-summary and embedding caches | purge job (worker), seconds later |
| In-flight processing | anything a still-running job writes after the delete | a second purge job, 40 minutes later (after the worker's job timeout) |

- Caches are keyed by content hash, not by document. So a deletion clears the organization's whole namespace for each of the three caches. The only cost is paying again for some captions or embeddings later.
- Rate-limit counters are not document content and are kept.
- The audit entry `document.delete` records how many answers were removed.
- **Organization deletion** erases all of the above for the whole organization (Phase 22). A lost deletion job is queued again by recovery (Phase 23).

Copies that outlive a deletion **by design**, with how long they last:
- **Database backups:** RDS snapshots and `backups/postgres/` dumps, until they expire (14 days by default).
- **Qdrant snapshots** in `backups/qdrant/`: keep retention at 30 days or less (`docs/reliability.md`).
- **S3 object versions:** if bucket versioning is on, keep a noncurrent-version expiry, e.g. 30 days.
- **Traces:** Langfuse only holds question and answer text when `LANGFUSE_CAPTURE_CONTENT=true`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MALWARE_SCAN` | `off` | `clamav` scans every upload before storage |
| `CLAMAV_HOST` / `CLAMAV_PORT` | `clamav` / `3310` | clamd address |
| `CLAMAV_TIMEOUT_S` | `120` | per-file scan timeout |
| `MALWARE_SCAN_ON_ERROR` | `reject` | `reject` (fail closed) or `allow` when the scanner gives no verdict |
| `PII_DETECTION_ENABLED` | `true` | count personal data per version |
| `PII_MASK_ANSWERS` | `false` | mask Aadhaar and card numbers in Assistant answers |
| `AWS_S3_KMS_KEY_ID` | — | SSE-KMS with a customer-managed key |
