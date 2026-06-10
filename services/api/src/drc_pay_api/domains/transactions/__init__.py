"""Transactions domain — the orchestration of a cross-network transfer.

``state_machine.py`` defines the explicit, enforced lifecycle of a transfer (collect
→ payout, with automatic refund on payout failure). The orchestration service that
drives pawaPay and posts to the ledger is built on top of it.
"""
