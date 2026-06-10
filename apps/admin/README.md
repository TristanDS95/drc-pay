# apps/admin

Internal support / operations dashboard. **Later — not in v1.**

When built: look up a transaction, see its ledger entries and state-machine history,
action a `manual_review` item, and watch operator health. Internal-only, behind SSO,
with strong audit logging on every action. Likely a small React/Next app talking to a
separate, privileged admin API surface (never the consumer API).
