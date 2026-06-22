# ADR 0008 — Repository restructure: flatten to backend/ + frontend/, drop placeholders

- **Status:** Accepted (2026-06-21). **Supersedes the top-level layout of [ADR 0002](./0002-monorepo-structure.md)** (the monorepo decision itself still stands).
- **Context:** ADR 0002 set up a forward-looking monorepo split — `apps/` (mobile, admin),
  `services/` (api, webhooks), `infra/`, `tooling/`, `docs/` — most of it placeholder folders for work
  not yet started. A year in, only two things are real: **one Python backend** (`services/api`) and
  **two static web front-ends** (`tooling/merchant-console`, `tooling/customer-app`). The empty
  scaffolding (`apps/`, `infra/`, `services/webhooks/`, `tooling/pawapay-sim/`) made the tree harder to
  read than the actual project. We want names that match reality and fewer files to wade through.
- **Decision:**
  - **Flatten `services/api/` → `backend/`.** It was the only real service, so the extra `services/`
    +`api/` nesting bought nothing. (The pawaPay **webhook receiver stays inside the backend**; the
    "own deployable" idea from ADR 0002 is deferred — see [`future-dev.md`](../future-dev.md).)
  - **Rename `tooling/` → `frontend/`.** With the standalone-simulator placeholder gone, it holds only
    the two web UIs, so `frontend/` is accurate.
  - **Remove the placeholder folders** `apps/` (mobile + admin), `infra/`, `services/webhooks/`,
    `tooling/pawapay-sim/`. Their plans are preserved in [`future-dev.md`](../future-dev.md); the
    mobile design tokens (the one non-placeholder file, `apps/mobile/src/theme/tokens.ts`) are
    preserved in [`design-tokens.md`](../design-tokens.md).
- **Consequences:**
  - The tree now reflects what exists: `backend/`, `frontend/`, `docs/`, plus root `Dockerfile` /
    `docker-compose.yml` / CI.
  - **Build/CI updated in lockstep:** `Dockerfile` `COPY` paths (`backend/…`, `frontend/…`),
    `.github/workflows/ci.yml` `working-directory: backend`, `.dockerignore`. Verified with the full
    test suite + an app boot after the move.
  - **Local dev paths change:** run from `backend/` (`cd backend`), and the venv lives at
    `backend/.venv`. The static-dir env vars point at `frontend/merchant-console` / `frontend/customer-app`.
  - Future work (mobile, admin, AWS infra, split webhook service, standalone sim) is now tracked as
    documentation in `future-dev.md` rather than empty folders — created when actually started.
- **Alternatives considered:**
  - **Keep `backend/api/` (nested) instead of flattening** — rejected: a single service doesn't need
    the level; re-introduce it only if we later split the backend into multiple deployables.
  - **Keep the placeholder folders** — rejected: they advertised structure we don't have and added
    noise; a docs file captures the intent without the empty dirs.
