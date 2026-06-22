# docs

Engineering-side documentation for drc-pay.

- **`adr/`** — Architecture Decision Records: one short file per significant,
  hard-to-reverse decision. Start from [`adr/_template.md`](./adr/_template.md).
- **[`DEVLOG.md`](./DEVLOG.md)** — the development log + handoff (read first to resume work); active roadmap.
- **[`future-dev.md`](./future-dev.md)** — longer-horizon / someday work (mobile app, admin dashboard,
  AWS infra, split webhook service), consolidated when the placeholder folders were removed (ADR 0008).
- **[`design-tokens.md`](./design-tokens.md)** — the design system (palette, type, spacing), mirroring
  the product spec's `ui-spec.md`.
- **Product spec** — the authoritative spec lives in the research workspace:
  [`../../drc-mvp-research/05-product-spec/`](../../drc-mvp-research/05-product-spec/)
  (human-readable summary: `../../drc-mvp-research/product-spec.html`). Port stable
  pieces here as they harden; **link rather than duplicate** while they're still
  moving, so there's one source of truth.
