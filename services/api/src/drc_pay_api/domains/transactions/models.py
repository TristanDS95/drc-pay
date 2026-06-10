"""Transaction model — the workflow record for one cross-network transfer.

Note: this row is a *workflow tracker*, not the source of truth for money. The
ledger (``domains.ledger``) is the source of truth; this just tracks where a transfer
is in its lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ledger.money import Money
from .state_machine import TxState


@dataclass
class Transaction:
    id: str
    payer_msisdn: str
    payee_msisdn: str
    amount: Money  # the amount delivered to the payee
    fee: Money  # our charge, same currency as amount (payer pays amount + fee)
    state: TxState
