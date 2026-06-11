"""Transaction orchestration — the payment spine.

Drives a cross-network money transfer through its two legs (collect from the payer,
pay out to the payee) keeping the state machine and the ledger in lock-step, with an
automatic refund if the payout fails after the collection already succeeded.

Outcomes from the payment rail are asynchronous: ``start_transaction`` kicks off the
collection, and the ``on_*_result`` handlers are invoked later by the webhook receiver
(or the reconciliation job). Every state change is enforced by the state machine, and
every money movement is recorded as a balanced ledger posting.

An optional ``Recorder`` narrates each step (validations, transitions, rail calls,
postings) so callers can surface a human-readable operations trace. It defaults to off
and is purely observational — it never affects behaviour.
"""
from __future__ import annotations

from ..ledger.ledger import Direction, Entry, Posting
from ..ledger.money import Money
from .models import Transaction
from .ports import LedgerPort, PaymentRail, Recorder, TransactionStore
from .state_machine import TxState, assert_transition

# Ledger account names. The persistent ledger will formalize these; here they are
# stable string keys so postings are legible.
PAYER = "payer:external"  # the payer's mobile-money wallet (outside our system)
PAYEE = "payee:external"  # the payee's mobile-money wallet (outside our system)
CLEARING = "pawapay:clearing"  # funds held at pawaPay mid-transfer
REVENUE = "revenue:fees"  # our fee income


class Orchestrator:
    def __init__(
        self,
        store: TransactionStore,
        rail: PaymentRail,
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

    def _post(self, posting: Posting) -> None:
        self._ledger.post(posting)
        detail = " | ".join(
            f"{e.direction.value.upper()} {e.account} {e.amount.to_major_str()} {e.amount.currency}"
            for e in posting.entries
        )
        self._rec(f"ledger · {detail} — balanced ✓")

    # ---- entry point --------------------------------------------------
    def start_transaction(
        self,
        *,
        transaction_id: str,
        payer_msisdn: str,
        payee_msisdn: str,
        amount: Money,
        fee: Money,
    ) -> Transaction:
        if amount.currency != fee.currency:
            raise ValueError("amount and fee must share a currency")
        if not amount.is_positive:
            raise ValueError("amount must be positive")
        self._rec("check · amount > 0 and amount/fee currency match — OK")
        transaction = Transaction(
            id=transaction_id,
            payer_msisdn=payer_msisdn,
            payee_msisdn=payee_msisdn,
            amount=amount,
            fee=fee,
            state=TxState.INITIATED,
            history=[TxState.INITIATED],
        )
        self._store.save(transaction)
        self._rec("state · created → initiated")
        self._transition(transaction, TxState.COLLECTION_PENDING)
        # The payer is charged amount + fee.
        self._rail.request_collection(
            transaction_id=transaction.id,
            msisdn=transaction.payer_msisdn,
            amount=amount + fee,
        )
        self._rec(f"rail → collect {(amount + fee).to_major_str()} {amount.currency} from {payer_msisdn}")
        return transaction

    # ---- collection leg ----------------------------------------------
    def on_collection_result(self, transaction_id: str, *, success: bool) -> None:
        transaction = self._store.get(transaction_id)
        self._rec(f"webhook ← pawaPay: collection {'SUCCEEDED' if success else 'FAILED'}")
        if not success:
            self._transition(transaction, TxState.COLLECTION_FAILED)
            self._rec("✕ ended — collection failed, no money moved")
            return
        self._transition(transaction, TxState.COLLECTION_SUCCEEDED)
        # Payer's funds (amount + fee) are now held at pawaPay.
        self._post(
            Posting(
                transaction_id=transaction.id,
                entries=(
                    Entry(PAYER, Direction.DEBIT, transaction.amount + transaction.fee),
                    Entry(CLEARING, Direction.CREDIT, transaction.amount + transaction.fee),
                ),
            )
        )
        self._begin_payout(transaction)

    def _begin_payout(self, transaction: Transaction) -> None:
        self._transition(transaction, TxState.PAYOUT_PENDING)
        self._rail.request_payout(
            transaction_id=transaction.id,
            msisdn=transaction.payee_msisdn,
            amount=transaction.amount,
        )
        self._rec(
            f"rail → pay {transaction.amount.to_major_str()} {transaction.amount.currency} "
            f"to {transaction.payee_msisdn}"
        )

    # ---- payout leg ---------------------------------------------------
    def on_payout_result(self, transaction_id: str, *, success: bool) -> None:
        transaction = self._store.get(transaction_id)
        self._rec(f"webhook ← pawaPay: payout {'SUCCEEDED' if success else 'FAILED'}")
        if not success:
            self._transition(transaction, TxState.PAYOUT_FAILED)
            self._begin_refund(transaction)
            return
        self._transition(transaction, TxState.PAYOUT_SUCCEEDED)
        # Deliver `amount` to the payee; keep `fee` as revenue. Clearing drains to zero.
        self._post(
            Posting(
                transaction_id=transaction.id,
                entries=(
                    Entry(CLEARING, Direction.DEBIT, transaction.amount + transaction.fee),
                    Entry(PAYEE, Direction.CREDIT, transaction.amount),
                    Entry(REVENUE, Direction.CREDIT, transaction.fee),
                ),
            )
        )
        self._rec("✓ complete — payout delivered, fee booked")

    # ---- refund -------------------------------------------------------
    def _begin_refund(self, transaction: Transaction) -> None:
        self._transition(transaction, TxState.REFUND_PENDING)
        self._rail.request_refund(transaction_id=transaction.id)
        self._rec("rail → refund (payout failed; returning funds to payer)")

    def on_refund_result(self, transaction_id: str, *, success: bool) -> None:
        transaction = self._store.get(transaction_id)
        self._rec(f"webhook ← pawaPay: refund {'SUCCEEDED' if success else 'FAILED'}")
        if not success:
            # Money is stuck at pawaPay — a human must resolve it.
            self._transition(transaction, TxState.MANUAL_REVIEW)
            self._rec("⚠ escalated to manual review — funds stuck at pawaPay")
            return
        self._transition(transaction, TxState.REFUNDED)
        # Return everything held back to the payer.
        self._post(
            Posting(
                transaction_id=transaction.id,
                entries=(
                    Entry(CLEARING, Direction.DEBIT, transaction.amount + transaction.fee),
                    Entry(PAYER, Direction.CREDIT, transaction.amount + transaction.fee),
                ),
            )
        )
        self._rec("✓ complete — payer made whole, no fee charged")

    # ---- internal -----------------------------------------------------
    def _transition(self, transaction: Transaction, destination: TxState) -> None:
        previous = transaction.state
        assert_transition(previous, destination)
        transaction.state = destination
        transaction.history.append(destination)
        self._store.save(transaction)
        self._rec(f"state · {previous.value} → {destination.value} (transition allowed ✓)")
