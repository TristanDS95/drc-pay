"""Reconciliation — the safety net.

To build. Periodically sweeps transactions stuck in a non-terminal state, queries
pawaPay's status API for the real outcome, and drives the state machine forward
(succeed, fail, refund, or escalate to manual_review). Assume webhooks WILL be missed;
this job guarantees eventual consistency regardless.
"""
