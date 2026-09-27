# Platform console (Phase 18)

The platform console is where the people who operate DocuNexa AI manage every organization. It lives at `/platform` in the frontend and `/api/v1/platform/...` in the API.

## Who can use it

Platform admins are a **separate identity** from organization users:

- **Accounts:** they have their own table (`platform_admins`), their own sign-in (`/platform/login`) and their own token audience (`docunexa:platform`).
- **Tokens do not cross:** a tenant token is refused by the console API, and a platform token is refused by every organization API. Organization accounts can never be promoted into the console.
- **Sessions:** platform sessions last at most a day. The frontend keeps them apart from organization sessions: separate storage keys, refresh endpoint and sign-in page.

There are two roles:

| Role | Can |
|---|---|
| `SUPER_ADMIN` | Everything: suspend or reactivate organizations, change plans and limits, activate or deactivate members, manage platform admins |
| `SUPPORT` | Read-only: overview, organizations, usage, members, audit log |

The first super admin is created from the command line; there is no public sign-up. The password is read from `PLATFORM_ADMIN_PASSWORD` or prompted for, never taken as an argument:

```bash
make platform-admin email=ops@yourcompany.com name="Ops"
# or: docker compose exec -it backend python -m app.platform_admin create --email … --name …
# forgotten password: python -m app.platform_admin reset-password --email …
```

Further admins are added in the console. Nobody can change their own platform role or status.

## What it shows — and what it never shows

- **Shown:** organizations with status, plan, limits and usage (active users, documents, storage, last activity), documents per file type, failed documents, and members (name, email, role, status, last sign-in).
- **Never shown:** no console endpoint returns a document, chunk, question or answer. Operators manage accounts and capacity, not customer content.

Console queries run on database sessions that are not bound to a tenant, so row-level security does not hide other organizations from them. The console tables (`platform_admins`, `platform_audit_logs`) grant nothing to the tenant role, so no organization session can read them.

## Suspending an organization

`PATCH /platform/organizations/{id}` with `{"status": "SUSPENDED", "suspended_reason": "…"}`. A reason is required, and it is recorded in the audit log.

- **Open sessions end at once:** an organization-wide revocation marker makes every access token stale ([sessions.py](../backend/app/core/sessions.py)).
- **Refresh is refused.**
- **Sign-in:** after a correct password, sign-in returns 403 `ORGANIZATION_SUSPENDED` with "Your organization's access is suspended. Contact support." The person has a valid account and needs to know why they cannot get in.
- **Nothing is deleted.** Reactivating (`{"status": "ACTIVE"}`) restores access.

## Plans and limits

| Plan | Active users | Documents | Storage |
|---|---|---|---|
| FREE | 5 | 200 | 2 GB |
| STARTER | 25 | 2,000 | 20 GB |
| BUSINESS | 100 | 20,000 | 200 GB |
| ENTERPRISE | unlimited | unlimited | unlimited |

- **Defaults:** organizations that sign up get `DEFAULT_PLAN` (FREE). Organizations that existed before Phase 18 were moved to BUSINESS.
- **Changing limits:** choosing a plan resets the limits to its defaults. Any limit can then be overridden per organization. Leaving a limit empty, or naming it in `unlimited`, makes it unlimited.
- **Where limits are checked:** when usage grows.
  - Adding or re-activating a user checks the user limit.
  - Uploading a new document checks the document limit.
  - Every upload checks storage.
- **Error:** a request over a limit gets 403 `PLAN_LIMIT_REACHED` with a message that says what to do.
- **Over the limit:** an organization over its limit (for example after a downgrade) keeps all its data. It just cannot add more.

## Audit

Every console action is written to `platform_audit_logs` with actor, action, target, organization, before/after values and client IP:
- sign-ins and failed sign-ins;
- organization changes;
- member changes;
- admin changes;
- command-line creation and password resets.

The Audit log page lists them newest first.

## API

| Method | Path | Role |
|---|---|---|
| POST | `/platform/auth/login`, `/auth/refresh`, `/auth/logout` | — (login is throttled like organization sign-in) |
| GET | `/platform/me`, `/overview`, `/plans` | any |
| GET | `/platform/organizations` (`q` also matches a member's email, `status`, `plan`, paging), `/organizations/{id}` | any |
| PATCH | `/platform/organizations/{id}` (status + reason, plan, limits, `unlimited`) | SUPER_ADMIN |
| PATCH | `/platform/organizations/{id}/members/{user_id}` (`is_active`) | SUPER_ADMIN |
| GET / POST / PATCH | `/platform/admins`, `/admins/{id}` | SUPER_ADMIN |
| GET | `/platform/audit` (`organization_id`, paging) | any |

## Later

These are not built yet:
- **MFA** for platform admins.
- **IP allow-listing** for `/platform`.
- **Billing integration** that sets the plan automatically.
- **Time-boxed, customer-approved support access**, if support ever needs to see an organization's content.
