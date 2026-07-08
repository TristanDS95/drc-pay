"""On-net (same-network) payment flow — facilitate & record (no money movement by us).

When the customer and merchant are on the SAME operator, we do NOT route money through pawaPay's
collect-then-payout. The customer pays the merchant **directly on the operator's own rail**; we never
touch the funds. Our job is only to RECORD the sale and mark it paid once it's confirmed — a single
balanced ledger posting (customer → merchant), no clearing, no pawaPay expense, no fee. The
cross-network two-leg flow stays in ``orchestrator.py``. See ADR 0009.

The confirmation is asynchronous: ``start`` records the payment as pending (awaiting confirmation),
and ``on_confirm`` resolves it — triggered by the merchant ("Confirm received") or, later, an operator
merchant-payment notification. Every state change is enforced by the state machine.
"""

from __future__ import annotations

from ..ledger.ledger import Direction, Entry, Posting
from ..ledger.money import Money
from .models import MERCHANT_ATTESTED, Transaction
from .orchestrator import (
    CUSTOMER,
    MERCHANT,
)  # the external-wallet account names, shared with the routed flow
from .ports import LedgerPort, Recorder, TransactionStore
from .state_machine import TxState, assert_transition


class OnNetOrchestrator:
    """Records a same-network payment that settles merchant-direct on the operator's rail. We hold no
    funds and take no fee: one balanced ledger posting (customer → merchant), confirmed out-of-band."""

    def __init__(
        self,
        store: TransactionStore,
        ledger: LedgerPort,
        recorder: Recorder | None = None,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._recorder = recorder

    def _rec(self, message: str) -> None:
        if self._recorder is not None:
            self._recorder.record(message)

    def _transition(self, transaction: Transaction, destination: TxState) -> None:
        previous = transaction.state
        assert_transition(previous, destination)
        transaction.state = destination
        transaction.history.append(destination)
        self._store.save(transaction)
        self._rec(f"state · {previous.value} → {destination.value} (transition allowed ✓)")

    # ---- entry point --------------------------------------------------
    def start(
        self,
        *,
        transaction_id: str,
        payer_msisdn: str,
        merchant_msisdn: str,
        amount: Money,
        provider: str,
        merchant_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Transaction:
        """Record a same-network payment as *pending confirmation*. We initiate nothing on the
        operator — the customer pays the merchant directly; the outcome arrives via ``on_confirm``.
        ``provider`` is the shared operator on both sides."""
        if not amount.is_positive:
            raise ValueError("amount must be positive")
        self._rec("check · amount > 0, same-network (on-net) — OK")
        transaction = Transaction(
            id=transaction_id,
            customer_msisdn=payer_msisdn,
            merchant_msisdn=merchant_msisdn,
            amount=amount,
            fee=Money(0, amount.currency),  # on-net: we take no cut and pay no pawaPay leg
            state=TxState.INITIATED,
            history=[TxState.INITIATED],
            idempotency_key=idempotency_key,
            customer_provider=provider,
            merchant_provider=provider,  # same network on both sides — that is what makes this on-net
            merchant_id=merchant_id,
            provenance=MERCHANT_ATTESTED,  # on-net is confirmed by the merchant, not a signed rail callback
        )
        self._store.save(transaction)
        self._rec("state · created → initiated")
        self._transition(transaction, TxState.COLLECTION_PENDING)  # awaiting confirmation
        self._rec(
            f"on-net · awaiting confirmation that {payer_msisdn} paid {merchant_msisdn} "
            f"{amount.to_major_str()} {amount.currency} directly on {provider}"
        )
        return transaction

    # ---- async outcome ------------------------------------------------
    def on_confirm(self, transaction_id: str, *, success: bool) -> None:
        """Resolve the confirmation (merchant "Confirm received", or later an operator notification).
        On success the merchant already has the money — record the single customer→merchant posting and
        mark the payment paid."""
        transaction = self._store.get(transaction_id)
        self._rec(f"confirm ← on-net payment {'CONFIRMED' if success else 'NOT RECEIVED'}")
        if not success:
            self._transition(transaction, TxState.COLLECTION_FAILED)
            self._rec("✕ ended — not received, no money moved")
            return
        # One leg: the customer's money went straight to the merchant on-net. We never held it, so
        # there is no clearing / expense / revenue — just the movement, recorded.
        self._ledger.post(
            Posting(
                transaction_id=transaction.id,
                entries=(
                    Entry(CUSTOMER, Direction.DEBIT, transaction.amount),
                    Entry(MERCHANT, Direction.CREDIT, transaction.amount),
                ),
            )
        )
        self._rec(
            f"ledger · DEBIT {CUSTOMER} {transaction.amount.to_major_str()} | "
            f"CREDIT {MERCHANT} {transaction.amount.to_major_str()} — balanced ✓"
        )
        self._transition(transaction, TxState.PAYOUT_SUCCEEDED)
        self._rec(
            "✓ complete — merchant paid directly on-net (no pawaPay, no fee, merchant-attested)"
        )
