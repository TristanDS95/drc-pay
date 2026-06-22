"""On-net (same-network) payment flow — the single-leg path.

When the customer and merchant are on the SAME operator, we don't route through pawaPay's
collect-then-payout (two legs, ~3.5–5%). The operator moves the money customer→merchant on its own
network in ONE leg (a direct C2B collection straight to the merchant); we never custody the funds,
so the ledger is a single balanced posting (customer → merchant) — no clearing, no pawaPay expense,
no fee leg. The cross-network two-leg flow stays in ``orchestrator.py``; a router picks between them.

The outcome is asynchronous (the operator's confirmation callback), resolved through ``on_confirm`` —
mirroring how the routed flow resolves via the webhook/sweep. Every state change is enforced by the
state machine; the one money movement is a balanced ledger posting.
"""
from __future__ import annotations

from ..ledger.ledger import Direction, Entry, Posting
from ..ledger.money import Money
from .models import Transaction
from .orchestrator import CUSTOMER, MERCHANT  # the external-wallet account names, shared with the routed flow
from .ports import DirectCollectRail, LedgerPort, RailRejected, Recorder, TransactionStore
from .state_machine import TxState, assert_transition


class OnNetOrchestrator:
    """Drives a same-network payment: one direct collection straight to the merchant, confirmed
    asynchronously. No payout leg, no custody, a single balanced ledger posting."""

    def __init__(
        self,
        store: TransactionStore,
        rail: DirectCollectRail,
        ledger: LedgerPort,
        recorder: Recorder | None = None,
    ) -> None:
        self._store = store
        self._rail = rail
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
        """Record a same-network payment and ask the operator to move the money customer→merchant
        directly. The outcome arrives later via ``on_confirm``. ``provider`` is the shared operator."""
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
        )
        self._store.save(transaction)
        self._rec("state · created → initiated")
        self._transition(transaction, TxState.COLLECTION_PENDING)
        try:
            op_id = self._rail.request_direct_collection(
                transaction_id=transaction.id,
                payer_msisdn=payer_msisdn,
                merchant_msisdn=merchant_msisdn,
                amount=amount,
                provider=provider,
            )
        except RailRejected as exc:
            self._rec(f"rail ✕ direct collection rejected synchronously — {exc}")
            self._transition(transaction, TxState.COLLECTION_FAILED)
            self._rec("✕ ended — collection rejected, no money moved")
            return transaction
        if op_id is not None:
            transaction.deposit_id = op_id  # the operator's op-id, so the callback correlates back
            self._store.save(transaction)
            self._rec(f"rail · direct_collect_id={op_id} (persisted)")
        self._rec(
            f"rail → on-net collect {amount.to_major_str()} {amount.currency} from {payer_msisdn} "
            f"straight to {merchant_msisdn} on {provider}"
        )
        return transaction

    # ---- async outcome ------------------------------------------------
    def on_confirm(self, transaction_id: str, *, success: bool) -> None:
        """Resolve the operator's confirmation. On success the merchant already has the money —
        record the single customer→merchant posting and mark the payment paid."""
        transaction = self._store.get(transaction_id)
        self._rec(f"callback ← operator: on-net collection {'SUCCEEDED' if success else 'FAILED'}")
        if not success:
            self._transition(transaction, TxState.COLLECTION_FAILED)
            self._rec("✕ ended — collection failed, no money moved")
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
        # On-net collapses the two legs: this single collection IS the settlement → paid.
        self._transition(transaction, TxState.PAYOUT_SUCCEEDED)
        self._rec("✓ complete — merchant paid directly on-net (no pawaPay, no fee leg)")
