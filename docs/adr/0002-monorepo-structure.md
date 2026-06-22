# ADR 0002 — Monorepo and repository structure

- **Status:** Accepted (2026-06-09). **Top-level layout superseded by [ADR 0008](./0008-repo-restructure.md)** — the monorepo decision still stands; the `apps/ services/ infra/ tooling/` split was flattened to `backend/ frontend/ docs/`.
- **Context:** One small team building a mobile app + backend + (later) an admin
  dashboard and a USSD gateway, plus infrastructure. Separate repos add version-skew
  and coordination cost at this size.
- **Decision:** A **single monorepo** (`drc-pay/`) located inside the existing
  `DRC Payment App/` workspace, **sibling to `drc-mvp-research/`**. Top-level split:
  `apps/` (mobile, admin), `services/` (api, webhooks), `infra/`, `tooling/`, `docs/`.
- **Consequences:**
  - Atomic cross-cutting changes, one CI pipeline, shared docs.
  - The webhook receiver is its **own deployable** — different security and
    availability profile from the authenticated user API.
  - GitHub + GitHub Actions for hosting and CI.
  - Because the backend is Python and mobile is TypeScript, there is no shared runtime
    `packages/` for now; the shared contract is the generated OpenAPI client.
- **Alternatives considered:** polyrepo — rejected: overhead unjustified at this team
  size.
