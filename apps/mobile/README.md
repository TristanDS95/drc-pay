# apps/mobile

The smartphone app — **React Native + Expo** (one codebase, iOS + Android).

**Not yet initialized.** To scaffold the Expo app in place:

    cd apps/mobile
    npx create-expo-app@latest .

Then adopt the structure below (feature-first, not file-type-first):

    src/
    ├── features/    # send, history, auth, profile — screens + hooks per feature
    ├── components/  # shared dumb UI (Button, AmountInput, PinPad)
    ├── api/         # client generated from the backend OpenAPI schema
    ├── lib/         # money formatting, MSISDN parse/validate, i18n (fr/)
    └── theme/       # design tokens — tokens.ts (coral/cream/charcoal, light + dark)

## Design

Mirrors `../../drc-mvp-research/05-product-spec/ui-spec.md`: Wave-style minimal, coral
accent, Inter, flat 12px-rounded components (no shadows), 3-tab nav (Envoyer /
Historique / Profil), French in v1. The palette and scale are already captured in
`src/theme/tokens.ts` so the spec and the code can't drift.

## Release

Via **EAS** with a **force-update** path — in a payments app you must be able to kill
a broken client version quickly. Staged rollout; never 100% of users at once.
