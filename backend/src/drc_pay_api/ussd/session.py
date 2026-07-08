"""USSD channel — a feature-phone-friendly way for a customer to pay a merchant.

The customer dials our shortcode (or **scans a QR that pre-fills it**) and pays by giving
the merchant's till and an amount. USSD aggregators (Africa's Talking, Infobip, …) manage
the session on their side and deliver the user's **full accumulated input** on every step
(`text = "1001*10*1"`). So we re-interpret that text positionally on every request —
`till * amount * choice` — and hold no server-side session of our own.

**Retries are part of the flow**: a mistyped till or amount re-prompts (CON) instead of
killing the session, and the parser simply skips the invalid entries when re-reading the
accumulated text. Three misses on any one field ends the session — a brake against menu
fuzzing and endless sessions, matching how operator menus behave.

A QR / dial-through is simply a session whose text **starts** pre-filled: `*123*1001#`
arrives as `text="1001"` (jump to the amount), `*123*1001*10#` as `text="1001*10"` (jump
straight to Confirm). Same handler, no special case.

**Menus are French by default** (the DRC's primary language; `DRCPAY_USSD_LANG=en` flips
the deployment). No in-menu language step: every extra step costs completion on USSD.
Replies stay well under the ~180-char USSD ceiling.

On confirmation we drive the **same** Orchestrator as the HTTP API via
`application.start_merchant_payment` — the money logic is never reimplemented. Same-network
payments route on-net (ADR 0009): nothing is initiated, and the closing message tells the
customer to pay the merchant's till (or number) directly. Adapting a specific aggregator's
wire format is a thin concern at the `/ussd` HTTP boundary (which also owns the shared
secret + rate limit); this handler is provider-neutral and offline-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..application.payments import start_merchant_payment
from ..container import Container
from ..domains.ledger.money import Money
from ..domains.merchants.models import Merchant
from ..domains.transactions.models import MERCHANT_ATTESTED

_CURRENCY = "USD"  # MVP: the USSD flow is single-currency for now
_MAX_AMOUNT = Money.from_major("10000", _CURRENCY)  # fat-finger guard, not a business rule
_MAX_ATTEMPTS = 3  # per field; the aggregator's own session timeout is the other backstop

# Every customer-facing string, per language. French first — it is the default.
_STRINGS: dict[str, dict[str, str]] = {
    "fr": {
        "ask_till": "Entrez le code du till marchand :",
        "bad_till": "Till inconnu. Entrez le code du till marchand :",
        "inactive_till": "Ce marchand n'accepte pas de paiements pour le moment.",
        "ask_amount": "Payer {name}\nEntrez le montant ({cur}) :",
        "bad_amount": "Montant invalide (0 a {max} {cur}). Entrez le montant :",
        "confirm": "Payer {amount} {cur} a {name} ?\n1. Confirmer\n2. Annuler",
        "cancelled": "Annule. Aucun paiement effectue.",
        "too_many": "Trop de tentatives. Veuillez recomposer.",
        "routed_done": (
            "Paiement de {amount} {cur} a {name} initie. Confirmez avec votre PIN "
            "mobile money sur votre telephone."
        ),
        "onnet_till_done": (
            "Payez {amount} {cur} a {name} directement : till {till} sur votre reseau. "
            "Le marchand confirme a reception."
        ),
        "onnet_msisdn_done": (
            "Payez {amount} {cur} a {name} directement au {msisdn} sur votre reseau. "
            "Le marchand confirme a reception."
        ),
    },
    "en": {
        "ask_till": "Enter merchant till code:",
        "bad_till": "Unknown till. Enter merchant till code:",
        "inactive_till": "This merchant is not accepting payments right now.",
        "ask_amount": "Pay {name}\nEnter amount ({cur}):",
        "bad_amount": "Invalid amount (0 to {max} {cur}). Enter amount:",
        "confirm": "Pay {amount} {cur} to {name}?\n1. Confirm\n2. Cancel",
        "cancelled": "Cancelled. No payment made.",
        "too_many": "Too many attempts. Please dial again.",
        "routed_done": (
            "Payment of {amount} {cur} to {name} initiated. Approve with your mobile "
            "money PIN on your phone."
        ),
        "onnet_till_done": (
            "Pay {amount} {cur} to {name} directly: till {till} on your network. "
            "The merchant confirms on receipt."
        ),
        "onnet_msisdn_done": (
            "Pay {amount} {cur} to {name} directly to {msisdn} on your network. "
            "The merchant confirms on receipt."
        ),
    },
}
# NOTE: deliberately ASCII-only (no accents). GSM-7 USSD transports mangle characters
# outside the basic set on some feature phones; "Annule" always renders, "Annulé" may not.


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
    """Re-reads the ``*``-joined text as ``till * amount * choice``, skipping invalid
    entries (each miss was already re-prompted on a previous step):

    ``""``            → ask for the till
    ``till``          → resolve the merchant, ask for the amount
    ``till*amount``   → ask to confirm
    ``till*amount*1`` → confirm → start the payment (routed or on-net)
    ``till*amount*2`` → cancel
    """

    def __init__(self, container: Container, lang: str = "fr") -> None:
        self._container = container
        self._s = _STRINGS.get(lang, _STRINGS["fr"])

    def _msg(self, key: str, **kwargs: str) -> str:
        return self._s[key].format(cur=_CURRENCY, max=_MAX_AMOUNT.to_major_str(), **kwargs)

    def handle(self, request: UssdRequest) -> UssdResponse:
        parts = [p for p in request.text.split("*") if p]
        idx = 0

        # --- till: consume parts until one resolves to an active merchant ---------------
        # An *unknown* code is treated as a typo — skipped, re-prompted (a genuine re-entry
        # arrives appended to the accumulated text). A *known but inactive* till is NOT a typo:
        # we END on it rather than skipping ahead, because skipping would let a later token
        # (e.g. a dial-through amount that happens to match another merchant's till) silently
        # retarget the payment to the wrong merchant.
        merchant: Merchant | None = None
        misses = 0
        while idx < len(parts):
            candidate = self._container.merchants.get_by_short_code(parts[idx])
            idx += 1
            if candidate is not None and candidate.is_active:
                merchant = candidate
                break
            if candidate is not None:  # real till, switched off — do not skip past it
                return UssdResponse.end(self._msg("inactive_till"))
            misses += 1
            if misses >= _MAX_ATTEMPTS:
                return UssdResponse.end(self._msg("too_many"))
        if merchant is None:
            return UssdResponse.con(self._msg("bad_till" if misses else "ask_till"))

        # --- amount: same retry pattern ---------------------------------------------------
        amount: Money | None = None
        misses = 0
        while idx < len(parts):
            candidate_amount = _parse_amount(parts[idx])
            idx += 1
            if candidate_amount is not None:
                amount = candidate_amount
                break
            misses += 1
            if misses >= _MAX_ATTEMPTS:
                return UssdResponse.end(self._msg("too_many"))
        if amount is None:
            key = "bad_amount" if misses else "ask_amount"
            return UssdResponse.con(self._msg(key, name=merchant.name))

        # --- confirm / cancel --------------------------------------------------------------
        confirmed: bool | None = None
        misses = 0
        while idx < len(parts):
            choice = parts[idx]
            idx += 1
            if choice == "1":
                confirmed = True
                break
            if choice == "2":
                confirmed = False
                break
            misses += 1
            if misses >= _MAX_ATTEMPTS:
                return UssdResponse.end(self._msg("too_many"))
        if confirmed is None:  # first ask, or re-ask after an invalid choice
            return UssdResponse.con(
                self._msg("confirm", amount=amount.to_major_str(), name=merchant.name)
            )
        if not confirmed:
            return UssdResponse.end(self._msg("cancelled"))

        on_net = self._start_payment(request.session_id, request.msisdn, merchant, amount)
        amount_str = amount.to_major_str()
        if on_net:
            # Same-network (ADR 0009): we moved nothing — the customer pays the merchant
            # directly on the operator's own rail; the merchant confirms receipt.
            if merchant.operator_till:
                return UssdResponse.end(
                    self._msg(
                        "onnet_till_done",
                        amount=amount_str,
                        name=merchant.name,
                        till=merchant.operator_till,
                    )
                )
            return UssdResponse.end(
                self._msg(
                    "onnet_msisdn_done",
                    amount=amount_str,
                    name=merchant.name,
                    msisdn=merchant.settlement_msisdn,
                )
            )
        return UssdResponse.end(self._msg("routed_done", amount=amount_str, name=merchant.name))

    def _start_payment(
        self, session_id: str, customer_msisdn: str, merchant: Merchant, amount: Money
    ) -> bool:
        """Start (or idempotently find) the payment; True when it routed on-net."""
        # Idempotency (CLAUDE.md: every money-moving request carries a key). Aggregators resend the
        # confirm step on timeout, and an unauthenticated caller could replay it. The key includes
        # the CUSTOMER msisdn: aggregators recycle session ids, and (session, till, amount) alone
        # would let a *different* customer's identical confirm resolve to this transaction — telling
        # them "paid" while nothing was initiated for their number. start_merchant_payment owns the
        # atomic find-or-create, so a concurrent resend can never open a second collection.
        key = f"ussd:{session_id}:{customer_msisdn}:{merchant.short_code}:{amount.amount_minor}"
        transaction_id = start_merchant_payment(
            store=self._container.store,
            ledger=self._container.ledger,
            rail=self._container.rail,
            predictor=self._container.predictor,
            simulated=self._container.simulated,
            customer_msisdn=customer_msisdn,
            merchant=merchant,
            amount=amount,
            idempotency_key=key,
        )
        return self._container.store.get(transaction_id).provenance == MERCHANT_ATTESTED


def _parse_amount(text: str) -> Money | None:
    """A positive amount within the sanity cap. Accepts the francophone comma decimal
    ('10,50'); rejects anything that isn't a plain decimal (scientific notation, digit
    separators, Unicode digits, thousands-grouped input) rather than silently misreading it."""
    try:
        amount = Money.from_user_input(text, _CURRENCY)
    except (ValueError, ArithmeticError):
        return None
    if not amount.is_positive or amount.amount_minor > _MAX_AMOUNT.amount_minor:
        return None
    return amount
