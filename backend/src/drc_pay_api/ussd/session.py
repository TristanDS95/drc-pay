"""USSD channel — a feature-phone-friendly way for a customer to pay a merchant.

The customer dials our shortcode (or **scans a QR that pre-fills it**) and pays by giving
the merchant's till and an amount. USSD aggregators (Africa's Talking, Infobip, …) manage
the session on their side and deliver the user's **full accumulated input** on every step
(`text = "1001*10*1"`). So we parse that text positionally — `till * amount * choice` —
and hold no server-side session of our own.

A QR / dial-through is simply a session whose text **starts** pre-filled: `*123*1001#`
arrives as `text="1001"` (jump to the amount), `*123*1001*10#` as `text="1001*10"` (jump
straight to Confirm). Same handler, no special case.

On confirmation we drive the **same** Orchestrator as the HTTP API via
`application.start_merchant_payment` — the money logic is never reimplemented. Adapting a
specific aggregator's wire format (form fields, field names) is a thin concern at the
`/ussd` HTTP boundary; this handler is provider-neutral and offline-testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..application.payments import start_merchant_payment
from ..domains.ledger.money import Money
from ..domains.merchants.models import Merchant
from ..http.container import Container

_CURRENCY = "USD"  # MVP: the USSD flow is single-currency for now


@dataclass
class UssdRequest:
    session_id: str
    msisdn: str
    text: str = ""  # the user's full accumulated input, "*"-joined ("" on the initial dial)


@dataclass
class UssdResponse:
    message: str
    continue_session: bool  # True keeps the session open (CON), False ends it (END)

    @classmethod
    def con(cls, message: str) -> UssdResponse:
        return cls(message=message, continue_session=True)

    @classmethod
    def end(cls, message: str) -> UssdResponse:
        return cls(message=message, continue_session=False)

    def to_wire(self) -> str:
        """Render to the conventional USSD reply string."""
        return f"{'CON' if self.continue_session else 'END'} {self.message}"


class UssdHandler:
    """Derives the step from the `*`-joined text and, on confirm, starts the payment:

    ``""``            → ask for the till
    ``till``          → resolve the merchant, ask for the amount
    ``till*amount``   → ask to confirm
    ``till*amount*1`` → confirm → start the payment
    ``till*amount*2`` → cancel
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    def handle(self, request: UssdRequest) -> UssdResponse:
        parts = [p for p in request.text.split("*") if p]
        if not parts:
            return UssdResponse.con("Enter merchant till code:")

        merchant = self._container.merchants.get_by_short_code(parts[0])
        if merchant is None or not merchant.is_active:
            return UssdResponse.end("Merchant not found.")
        if len(parts) == 1:
            return UssdResponse.con(f"Pay {merchant.name}\nEnter amount ({_CURRENCY}):")

        amount = _parse_amount(parts[1])
        if amount is None:
            return UssdResponse.end("Invalid amount. Please dial again.")
        if len(parts) == 2:
            return UssdResponse.con(
                f"Pay {amount.to_major_str()} {_CURRENCY} to {merchant.name}?\n1. Confirm\n2. Cancel"
            )

        choice = parts[2]
        if choice == "2":
            return UssdResponse.end("Cancelled.")
        if choice != "1":
            return UssdResponse.end("Invalid choice. Please dial again.")
        self._start_payment(request.msisdn, merchant, amount)
        return UssdResponse.end(
            f"Payment of {amount.to_major_str()} {_CURRENCY} to {merchant.name} "
            "initiated. Approve on your phone."
        )

    def _start_payment(self, customer_msisdn: str, merchant: Merchant, amount: Money) -> None:
        start_merchant_payment(
            store=self._container.store,
            ledger=self._container.ledger,
            rail=self._container.rail,
            predictor=self._container.predictor,
            simulated=self._container.simulated,
            customer_msisdn=customer_msisdn,
            merchant=merchant,
            amount=amount,
        )


def _parse_amount(text: str) -> Money | None:
    try:
        amount = Money.from_major(text, _CURRENCY)
    except (ValueError, ArithmeticError):
        return None
    return amount if amount.is_positive else None


def run_session(
    handler: UssdHandler, session_id: str, msisdn: str, inputs: list[str]
) -> list[UssdResponse]:
    """Simulate an aggregator driving a whole conversation: the initial dial, then each
    input — sending the **accumulated** text each step, as real aggregators do. Returns
    every response (the last is the terminal END)."""
    responses = [handler.handle(UssdRequest(session_id, msisdn, ""))]
    accumulated: list[str] = []
    for value in inputs:
        accumulated.append(value)
        responses.append(handler.handle(UssdRequest(session_id, msisdn, "*".join(accumulated))))
    return responses
