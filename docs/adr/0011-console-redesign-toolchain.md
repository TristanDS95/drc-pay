# ADR 0011 - Merchant console redesign: a Vite + Svelte + Tailwind toolchain

- **Status:** Accepted (2026-07-22)

- **Context:**
  With the backend feature-complete for the MVP, the merchant console is now the single most
  important surface - it is what a real merchant sees and judges the product by. The existing
  console (`frontend/merchant-console/index.html`) is one hand-written, zero-build static file:
  fast to ship and deploy, but it had drifted into a "developer dashboard" look, and its single-
  file, string-templated structure does not scale to the fuller, multi-screen, premium redesign we
  want (Overview / Payments / Customers / Settings, light **and** dark, an installable PWA, a real
  component-driven design system).

  The project has deliberately avoided a frontend build step until now (documented in the READMEs
  and DEVLOG). Introducing one is a real architecture change, so it is recorded here.

- **Decision:**
  Build a redesigned console as a new **Vite + Svelte 5 + Tailwind CSS v4** app at
  `frontend/console/`, under a new brand identity (**InterPay**; see the design tokens). Key
  choices:
  - **Svelte** for the component layer - it compiles to small vanilla JS with almost no runtime, so
    the premium result stays light on the modest Android phones our merchants use (the initial
    Overview build is ~20 KB gzipped JS + ~4 KB CSS).
  - **Tailwind v4** with a CSS-first `@theme` token system in `src/app.css`. Semantic tokens
    (`canvas`, `surface`, `ink`, `brand`, …) switch by `[data-theme]` on `<html>`, so light and dark
    are both first-class from day one rather than a retrofit.
  - **Fonts:** Inter for UI, Fraunces (serif) for headlines and money figures - the "A+B blend"
    chosen during the design exploration.
  - **Built in parallel:** the existing `merchant-console` keeps serving the live app untouched; we
    cut `DRCPAY_CONSOLE_DIR` over to the new build's `dist/` only once the redesign is complete and
    verified. Zero mid-build disruption.
  - **Deploy:** the single-container Docker image gains a **multi-stage build** - a Node stage
    compiles `frontend/console` to static assets, the Python stage serves them. The app is still
    served same-origin by FastAPI; only the build gains a compile step. (Wired in the cutover phase.)

- **Consequences:**
  - *Easier:* a real design system and component reuse; light + dark for free; multi-screen
    structure; a path to an installable PWA; a premium, maintainable UI.
  - *Harder / new cost:* the repo now has a Node toolchain and a build step for one frontend; CI and
    the Dockerfile must run `npm ci && npm run build`; contributors need Node to work on the console.
    The customer and staff pages stay zero-build static for now - the toolchain is scoped to the
    console where it earns its keep.
  - Nothing about the backend, the money core, or the deploy topology (same-origin static serving)
    changes.

- **Alternatives considered:**
  - **Keep the single static file** - lowest friction, but no leverage for a multi-screen premium
    redesign and a real design system; the reason we are here.
  - **Tailwind only, no framework** - lightest toolchain, but multi-screen state and components stay
    manual; too little leverage for the "fuller restructure" scope.
  - **React instead of Svelte** - most familiar for future hires, but a heavier runtime on cheap
    phones; Svelte fits the performance constraint better. Revisit only if hiring makes React's
    ecosystem decisive.
