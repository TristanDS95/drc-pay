# tooling/pawapay-sim

A **standalone HTTP fake of pawaPay** for offline, deterministic testing — **not built
yet, and possibly not needed.**

## First, the thing that already exists

The API has an **in-process** simulator,
`services/api/.../integrations/pawapay/simulator.py` (`SimulatedPaymentRail`). It
implements the domain `PaymentRail` port, records each collection / payout / refund,
and lets the caller drive outcomes via the orchestrator's `on_*_result` handlers. That
covers the unit tests and the API-level demo (the `scenario` field on
`POST /transactions`) with **zero network**. For testing the backend, that's enough.

## When this standalone sim earns its place

Build this **only** once we have a separate `services/webhooks` deployable and want to
test the *real* asynchronous path end-to-end: a process that accepts pawaPay-shaped
collection/payout/refund requests over HTTP and later **fires signed webhooks**
(RFC-9421 public-key) back at `services/webhooks`, so we can exercise missed-webhook →
reconciliation against actual network calls.

Until then, prefer the in-process `SimulatedPaymentRail`. Don't duplicate its logic
here.
