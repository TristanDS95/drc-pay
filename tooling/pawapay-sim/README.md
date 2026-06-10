# tooling/pawapay-sim

A **local fake of pawaPay** so the whole app can be built and tested offline — before,
and alongside, real sandbox access.

It implements the same interface the real client does (the `PawaPayClient` Protocol in
`services/api/.../integrations/pawapay`): request a collection, request a payout,
request a refund, query status — and can fire **signed webhooks** back at
`services/webhooks` to exercise the full flow, including payout-failure → refund and
missed-webhook → reconciliation.

**Why:** deterministic tests, no network, no waiting on sandbox credentials, and a safe
place to simulate every failure mode on demand.
