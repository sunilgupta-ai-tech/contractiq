# SaaS features (Phase 22)

## Organizations

| Action | Who | How |
|---|---|---|
| Create | Anyone (self sign-up) | `POST /auth/register`: the creator becomes the Admin and the organization starts on `DEFAULT_PLAN` (FREE) |
| Suspend / reactivate | Platform super admin | [platform.md](platform.md) |
| **Delete** | Platform super admin | `DELETE /platform/organizations/{id}` with `{"confirm_name": "<exact name>"}` |

What deletion does:

1. **Right away:** the organization becomes `DELETING`. Every session of its users ends and sign-in is refused.
2. **In the background:** a worker job ([`delete_organization`](../workers/app/tasks/organization.py)) erases:
   - every vector (tenant filter in Qdrant);
   - every file (`tenants/<id>/`: originals, parsed text, chunks, images, analysis caches);
   - every cache entry (`ciq:<id>:*`);
   - the organization row, which removes every tenant table by `ON DELETE CASCADE`.
3. **Afterwards:** a record (who asked, when, the name) stays in the platform audit log.

Each step is idempotent, so a retried job finishes the work. A job for an organization that was reactivated meanwhile does nothing.

## Users, invitations, roles, permissions

- **Add directly.** An admin can add a user with a temporary password (Team → Members), as before.
- **Invite by link** (Team → Invite by link):
  - The admin picks an email and a role and gets a link `/invite/<token>` to share.
  - The invitee opens it, chooses a password and is signed in.
  - The token is 256 bits of randomness; only its SHA-256 is stored. Links work once, expire after `INVITATION_TTL_DAYS` (7) and can be revoked.
  - The same rules as adding a user apply: the email must be unique, the role must be within the inviter's access, and the plan's user limit is checked again when the seat is taken.
  - Wrong tokens are throttled per IP.
- **Roles and permissions** work as in [security.md](security.md) (Phase 17 and Phase 20).

No email is sent yet. Wiring an email provider (SES, SendGrid) only changes where the link goes.

## Plans and limits

| Plan | Users | Documents | Storage | AI questions / month | AI tokens / month |
|---|---|---|---|---|---|
| FREE | 5 | 200 | 2 GB | 500 | 1 M |
| STARTER | 25 | 2,000 | 20 GB | 5,000 | 10 M |
| BUSINESS | 100 | 20,000 | 200 GB | 20,000 | 40 M |
| ENTERPRISE | unlimited | unlimited | unlimited | unlimited | unlimited |

- **Overrides:** the platform console can override any limit per organization.
- **When AI limits apply:** before any model call — questions (`/query`) and analyses (`/contracts/*`) — with 403 `PLAN_LIMIT_REACHED`. Documents already uploaded still finish processing.

## Usage tracking

Every model and embedding call is counted for the organization it serves:
- the answer and planning calls of a question;
- analysis calls;
- processing calls: embeddings, image captions, table summaries, handwriting transcription.

Mechanism ([usage.py](../backend/app/services/usage.py)):
- A **tally** is opened for each piece of work, and the monitoring wrappers add every call's tokens to it, including concurrent calls deep in the pipeline.
- When the work ends, one atomic upsert adds the tally to `usage_counters` for the organization and month.
- Counters live in PostgreSQL, not Redis, because they drive limits and billing.
- Embedding tokens are estimated from text length.

Where to see it:
- Admins: **Usage** page (`GET /usage`) — this month against the plan, the last six months, storage, documents and users.
- Platform admins: the same numbers on each organization's page.

## Audit log

Admins see the organization's log at **Audit log** (`GET /audit-logs`, filters by action prefix such as `document.` and by actor). Recorded:

| Area | Actions |
|---|---|
| Sign-in | `auth.login`, `auth.login_failed`, `auth.register` |
| Documents | `document.upload`, **`document.download`**, `document.delete`, `document.access`, `document.reviewed` |
| AI | **`query.run`** — who asked, when, scope size, outcome, tokens; not the question itself, which stays in the user's private conversation |
| People | `user.create`, `user.update`, `role.create/update/delete`, `invitation.create/accept/revoke` |

Downloads go through `GET /documents/{id}/versions/{version_id}/download`:
- the file is streamed, never loaded into memory;
- the visibility rules of Phase 20 apply;
- the file is offered under its original name.

Entries hold IDs and parameters only, never document text, so the log is safe to show and export.

## Versioning

V1, V2, V3… per document with version-to-version comparison (Phases 3 and 10). This phase does not change it.
