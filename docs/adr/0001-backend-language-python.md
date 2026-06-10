# ADR 0001 — Backend language: Python (FastAPI)

- **Status:** Accepted (2026-06-09)
- **Context:** The mobile app is TypeScript (React Native / Expo). The backend could be
  Node/TypeScript (maximum code-sharing for a small team, one language) or
  Python/FastAPI (matches Wave; stronger ecosystem for the fraud/credit ML that the
  comparables research identifies as the real long-term value).
- **Decision:** **Python with FastAPI** for `services/api`.
- **Consequences:**
  - This is a **two-toolchain monorepo** (TS mobile + Python backend), not a
    shared-code one. The client/server contract is shared via the API's **OpenAPI
    schema** (generate the mobile client from it), not imported code.
  - Tooling: ruff + mypy (strict) + pytest; `src` layout.
  - The hired backend engineer owns refinements within Python; revisit the language
    only with strong cause.
- **Alternatives considered:** Node/TypeScript — rejected for now: weaker ML story,
  and the code-sharing benefit is modest once contracts are generated.
