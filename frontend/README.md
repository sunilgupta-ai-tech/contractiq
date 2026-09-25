# ContractIQ — Frontend

Next.js 15 (App Router) · React 19 · TypeScript (strict) · Tailwind CSS.

```bash
npm install
npm run dev        # http://localhost:3000
npm test           # vitest
npm run lint && npm run typecheck
```

## Structure

| Folder | Contents |
|---|---|
| `app/` | Routes only. `(workspace)/` uses the app shell; `login/` stands alone. |
| `features/` | Feature modules (dashboard, documents, assistant, compare, risk, system, auth) — the page-level components and their logic. |
| `components/ui` | Design-system primitives: Button, Badge, Card, StatusPill, PipelineStepper, RiskBadge, states. |
| `components/layout` | Sidebar, Topbar, AppShell (responsive drawer on mobile). |
| `services/` | API access per domain. The **only** place that decides demo vs live data. |
| `lib/` | `api-client` (envelope parsing, `ApiError` with request ID, timeouts), public config, demo fixtures. |
| `hooks/` | `useAsync` (stale-safe fetching), `useInterval` (polling). |
| `types/` | Domain types mirroring backend schemas. |
| `utils/` | Formatting, validation, word-level clause diff. |

## Design system

"Legal paper": warm paper canvas, ink typography, deep-navy navigation rail, verdigris as the single action color, and highlighter amber reserved for cited evidence. Fraunces (display serif), Inter (UI) and JetBrains Mono (clause refs, IDs) are self-hosted from npm. All colors are CSS variables in `app/globals.css` with a full dark theme via `prefers-color-scheme`.

## Configuration

Only `NEXT_PUBLIC_*` variables reach the browser, and they are inlined at **build** time:

* `NEXT_PUBLIC_API_BASE_URL` — API origin (default `http://localhost:8000`)
* `NEXT_PUBLIC_USE_DEMO_DATA` — `true` until the backend phase for a feature lands. The System health page always uses the live API.

Never put secrets (e.g. `GEMINI_API_KEY`) in `NEXT_PUBLIC_*`.
