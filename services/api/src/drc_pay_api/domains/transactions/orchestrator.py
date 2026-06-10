"""Transfer orchestration — the payment spine.

Drives a cross-network transfer through its two legs (collect from the payer, pay out
to the payee) keeping the state machine and the ledger in lock-step, with an automatic
refund if the payout fails after the collection already succeeded.

Outcomes from the payment rail are asynchronous: ``start_transfer`` kicks off the
collection, and the ``on_*_result`` handlers are invoked later by the webhook receiver
(or the reconciliation job). Every state change is enforced by the state machine, and
every money movement is recorded as a balanced ledger posting.
"""
from __future__ import annotations

from ..ledger.ledger import Direction, Entry, Posting
from ..ledger.money import Money
from .models import Transaction
from .ports import LedgerPort, PaymentRail, TransactionStore
from .state_machine import TxState, assert_transition

# Ledger account names. The persistent ledger will formalize these; here they are
# stable string keys so postings are legible.
PAYER = "payer:external"  # the payer's mobile-money wallet (outside our system)
PAYEE = "payee:external"  # the payee's mobile-money wallet (outside our system)
CLEARING = "pawapay:clearing"  # funds held at pawaPay mid-transfer
REVENUE = "revenue:fees"  # our fee income


class Orchestrator:
    def __init__(self, store: TransactionStore, rail: PaymentRail, ledger: LedgerPort) -> None:
        self._store = store
        self._rail = rail
        self._ledger = ledger

    # ---- entry point --------------------------------------------------
    def start_transfer(
        self,
        *,
        transfer_id: str,
        payer_msisdn: str,
        payee_msisdn: str,
        amount: Money,
        fee: Money,
    ) -> Transaction:
        if amount.currency != fee.currency:
            raise ValueError("amount and fee must share a currency")
        if not amount.is_positive:
            raise ValueError("amount must be positive")
        transaction = Transaction(
            id=transfer_id,
            payer_msisdn=payer_msisdn,
            payee_msisdn=payee_msisdn,
            amount=amount,
            fee=fee,
            state=TxState.INITIATED,
            history=[TxState.INITIATED],
        )
        self._store.save(transaction)
        self._transition(transaction, TxState.COLLECTION_PENDING)
        # The payer is charged amount + fee.
        self._rail.request_collection(
            transfer_id=transaction.id,
            msisdn=transaction.payer_msisdn,
            amount=amount + fee,
        )
        return transaction

    # ---- collection leg ----------------------------------------------
    def on_collection_result(self, transfer_id: str, *, success: bool) -> None:
        transaction = self._store.get(transfer_id)
        if not success:
            self._transition(transaction, TxState.COLLECTION_FAILED)
            return
        self._transition(transaction, TxState.COLLECTION_SUCCEEDED)
        # Payer's funds (amount + fee) are now held at pawaPay.
        self._ledger.post(
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
            transfer_id=transaction.id,
            msisdn=transaction.payee_msisdn,
            amount=transaction.amount,
        )

    # ---- payout leg ---------------------------------------------------
    def on_payout_result(self, transfer_id: str, *, success: bool) -> None:
        transaction = self._store.get(transfer_id)
        if not success:
            self._transition(transaction, TxState.PAYOUT_FAILED)
            self._begin_refund(transaction)
            return
        self._transition(transaction, TxState.PAYOUT_SUCCEEDED)
        # Deliver `amount` to the payee; keep `fee` as revenue. Clearing drains to zero.
        self._ledger.post(
            Posting(
                transaction_id=transaction.id,
                entries=(
                    Entry(CLEARING, Direction.DEBIT, transaction.amount + transaction.fee),
                    Entry(PAYEE, Direction.CREDIT, transaction.amount),
                    Entry(REVENUE, Direction.CREDIT, transaction.fee),
                ),
            )
        )

    # ---- refund -------------------------------------------------------
    def _begin_refund(self, transaction: Transaction) -> None:
        self._transition(transaction, TxState.REFUND_PENDING)
        self._rail.request_refund(transfer_id=transaction.id)

    def on_refund_result(self, transfer_id: str, *, success: bool) -> None:
        transaction = self._store.get(transfer_id)
        if not success:
            # Money is stuck at pawaPay — a human must resolve it.
            self._transition(transaction, TxState.MANUAL_REVIEW)
            return
        self._transition(transaction, TxState.REFUNDED)
        # Return everything held back to the payer.
        self._ledger.post(
            Posting(
                transaction_id=transaction.id,
                entries=(
                    Entry(CLEARING, Direction.DEBIT, transaction.amount + transaction.fee),
                    Entry(PAYER, Direction.CREDIT, transaction.amount + transaction.fee),
                ),
            )
        )

    # ---- internal -----------------------------------------------------
    def _transition(self, transaction: Transaction, destination: TxState) -> None:
        assert_transition(transaction.state, destination)
        transaction.state = destination
        transaction.history.append(destination)
        self._store.save(transaction)
