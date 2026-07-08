"""Transaction orchestration — the payment spine.

Drives a customer→merchant payment through its two legs (collect from the customer, then
settle to the merchant) keeping the state machine and the ledger in lock-step, with an
automatic refund to the customer if the settlement fails after the collection already
succeeded.

Fee model (merchant acquiring): the customer pays the sticker ``amount``; the merchant
absorbs our fee (MDR) and nets ``amount − fee``; we keep ``fee`` as revenue, booked only
on a successful settlement. A refund returns the full ``amount`` to the customer (no fee).

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
from .ports import LedgerPort, PaymentRail, RailRejected, Recorder, TransactionStore
from .pricing import collection_cost, payout_cost
from .state_machine import TxState, assert_transition

# Ledger account names. The persistent ledger will formalize these; here they are
# stable string keys so postings are legible.
CUSTOMER = "customer:external"  # the customer's mobile-money wallet (outside our system)
MERCHANT = "merchant:external"  # the merchant's settlement wallet (outside our system)
CLEARING = "pawapay:clearing"  # funds held at pawaPay mid-transfer
REVENUE = "revenue:fees"  # our margin: the MDR left over after pawaPay's cost
EXPENSE = "expense:pawapay"  # what pawaPay charges us to move the money (cost of the rails)


def _require_provider(provider: str | None, *, leg: str) -> str:
    """A money-moving leg must know the operator. Providers are captured at
    ``start_transaction``; a missing one here is a data error, not an edge case."""
    if not provider:
        raise ValueError(f"transaction is missing the {leg} provider")
    return provider


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
        customer_msisdn: str,
        merchant_msisdn: str,
        amount: Money,
        fee: Money,
        customer_provider: str,
        merchant_provider: str,
        merchant_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Transaction:
        if amount.currency != fee.currency:
            raise ValueError("amount and fee must share a currency")
        if not amount.is_positive:
            raise ValueError("amount must be positive")
        if fee.amount_minor >= amount.amount_minor:
            raise ValueError("fee must be less than the amount")
        self._rec("check · amount > 0, fee < amount, currencies match — OK")
        self._rec(
            f"pricing · fee = {fee.to_major_str()} {amount.currency} "
            f"· merchant nets {(amount - fee).to_major_str()} {amount.currency}"
        )
        transaction = Transaction(
            id=transaction_id,
            customer_msisdn=customer_msisdn,
            merchant_msisdn=merchant_msisdn,
            amount=amount,
            fee=fee,
            state=TxState.INITIATED,
            history=[TxState.INITIATED],
            idempotency_key=idempotency_key,
            customer_provider=customer_provider,
            merchant_provider=merchant_provider,
            merchant_id=merchant_id,
        )
        self._store.save(transaction)
        self._rec("state · created → initiated")
        self._transition(transaction, TxState.COLLECTION_PENDING)
        # The customer pays the sticker amount, on the customer's own operator.
        try:
            deposit_id = self._rail.request_collection(
                transaction_id=transaction.id,
                msisdn=transaction.customer_msisdn,
                amount=amount,
                provider=customer_provider,
            )
        except RailRejected as exc:
            self._rec(f"rail ✕ collection rejected synchronously — {exc}")
            self._transition(transaction, TxState.COLLECTION_FAILED)
            self._rec("✕ ended — collection rejected, no money moved")
            return transaction
        self._store_op_id(transaction, kind="deposit", op_id=deposit_id)
        self._rec(
            f"rail → collect {amount.to_major_str()} {amount.currency} from {customer_msisdn}"
        )
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
        # The customer's funds land at pawaPay, less pawaPay's collection fee — which it deducts
        # right after collection (their docs: "fees will be deducted from that amount after the
        # collection has completed"). We book that fee as our cost — an expense, never revenue —
        # estimated from pawaPay's published per-leg rate. If the payout later fails and we
        # refund, this fee is already booked, so the refund correctly shows it as a real loss.
        collect_cost = collection_cost(
            transaction.amount, _require_provider(transaction.customer_provider, leg="customer")
        )
        entries = [
            Entry(CUSTOMER, Direction.DEBIT, transaction.amount),
            Entry(CLEARING, Direction.CREDIT, transaction.amount - collect_cost),
        ]
        if collect_cost.is_positive:
            entries.append(Entry(EXPENSE, Direction.CREDIT, collect_cost))
        self._post(Posting(transaction_id=transaction.id, entries=tuple(entries)))
        self._begin_payout(transaction)

    def _begin_payout(self, transaction: Transaction) -> None:
        self._transition(transaction, TxState.PAYOUT_PENDING)
        # The merchant nets amount − fee (it absorbs the fee), on the merchant's operator.
        merchant_amount = transaction.amount - transaction.fee
        try:
            payout_id = self._rail.request_payout(
                transaction_id=transaction.id,
                msisdn=transaction.merchant_msisdn,
                amount=merchant_amount,
                provider=_require_provider(transaction.merchant_provider, leg="merchant"),
            )
        except RailRejected as exc:
            self._rec(f"rail ✕ settlement rejected synchronously — {exc}")
            self._transition(transaction, TxState.PAYOUT_FAILED)
            self._begin_refund(transaction)
            return
        self._store_op_id(transaction, kind="payout", op_id=payout_id)
        self._rec(
            f"rail → settle {merchant_amount.to_major_str()} {merchant_amount.currency} "
            f"to {transaction.merchant_msisdn}"
        )

    # ---- payout leg ---------------------------------------------------
    def on_payout_result(self, transaction_id: str, *, success: bool) -> None:
        transaction = self._store.get(transaction_id)
        self._rec(f"webhook ← pawaPay: settlement {'SUCCEEDED' if success else 'FAILED'}")
        if not success:
            self._transition(transaction, TxState.PAYOUT_FAILED)
            self._begin_refund(transaction)
            return
        self._transition(transaction, TxState.PAYOUT_SUCCEEDED)
        # Settle amount − fee (the MDR) to the merchant. The fee splits two ways: pawaPay's
        # payout-leg cost (an expense) and whatever is left over — our margin — booked to
        # revenue. Clearing holds the post-collection-fee balance and drains to zero across the
        # two legs. With no margin set, the MDR equals cost, so revenue is zero (we keep nothing).
        collect_cost = collection_cost(
            transaction.amount, _require_provider(transaction.customer_provider, leg="customer")
        )
        pay_cost = payout_cost(
            transaction.amount, _require_provider(transaction.merchant_provider, leg="merchant")
        )
        merchant_amount = transaction.amount - transaction.fee
        margin = transaction.fee - collect_cost - pay_cost  # MDR − round-trip cost
        entries = [
            Entry(CLEARING, Direction.DEBIT, transaction.amount - collect_cost),
            Entry(MERCHANT, Direction.CREDIT, merchant_amount),
        ]
        if pay_cost.is_positive:
            entries.append(Entry(EXPENSE, Direction.CREDIT, pay_cost))
        if margin.is_positive:
            entries.append(Entry(REVENUE, Direction.CREDIT, margin))
        self._post(Posting(transaction_id=transaction.id, entries=tuple(entries)))
        self._rec("✓ complete — merchant settled · rails cost → expense · margin → revenue")

    # ---- refund -------------------------------------------------------
    def _begin_refund(self, transaction: Transaction) -> None:
        self._transition(transaction, TxState.REFUND_PENDING)
        # Refund the full amount the customer paid, against the original deposit; the
        # customer's operator formats the amount to the right decimal precision.
        try:
            refund_id = self._rail.request_refund(
                transaction_id=transaction.id,
                deposit_id=transaction.deposit_id,
                amount=transaction.amount,
                provider=_require_provider(transaction.customer_provider, leg="customer"),
            )
        except RailRejected as exc:
            self._rec(f"rail ✕ refund rejected synchronously — {exc}")
            self._transition(transaction, TxState.MANUAL_REVIEW)
            self._rec("⚠ escalated to manual review — refund could not be initiated")
            return
        self._store_op_id(transaction, kind="refund", op_id=refund_id)
        self._rec("rail → refund (settlement failed; returning funds to the customer)")

    def on_refund_result(self, transaction_id: str, *, success: bool) -> None:
        transaction = self._store.get(transaction_id)
        self._rec(f"webhook ← pawaPay: refund {'SUCCEEDED' if success else 'FAILED'}")
        if not success:
            # Money is stuck at pawaPay — a human must resolve it.
            self._transition(transaction, TxState.MANUAL_REVIEW)
            self._rec("⚠ escalated to manual review — funds stuck at pawaPay")
            return
        self._transition(transaction, TxState.REFUNDED)
        # Return everything held back to the customer.
        self._post(
            Posting(
                transaction_id=transaction.id,
                entries=(
                    Entry(CLEARING, Direction.DEBIT, transaction.amount),
                    Entry(CUSTOMER, Direction.CREDIT, transaction.amount),
                ),
            )
        )
        self._rec("✓ complete — customer made whole, no fee charged")

    # ---- internal -----------------------------------------------------
    def _store_op_id(self, transaction: Transaction, *, kind: str, op_id: str | None) -> None:
        """Persist a pawaPay op-id on the transaction, if the rail issued one. The
        simulator returns ``None`` (no real operation), so nothing is stored then."""
        if op_id is None:
            return
        if kind == "deposit":
            transaction.deposit_id = op_id
        elif kind == "payout":
            transaction.payout_id = op_id
        else:
            transaction.refund_id = op_id
        self._store.save(transaction)
        self._rec(f"rail · {kind}_id={op_id} (persisted)")

    def _transition(self, transaction: Transaction, destination: TxState) -> None:
        previous = transaction.state
        assert_transition(previous, destination)
        transaction.state = destination
        transaction.history.append(destination)
        self._store.save(transaction)
        self._rec(f"state · {previous.value} → {destination.value} (transition allowed ✓)")
