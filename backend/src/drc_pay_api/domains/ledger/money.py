"""Money as integer minor units. Never floats.

A payments system must never represent money as a binary float: ``0.1 + 0.2`` is not
``0.3`` in IEEE-754, and those rounding errors compound across a ledger until the
books no longer balance. We store every amount as an integer number of *minor units*
(US cents, Congolese centimes) tagged with an ISO-4217 currency code, and we only
ever parse human input through ``Decimal`` (exact) — never ``float``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# A *plain* human-typed amount: ASCII digits with an optional single decimal separator
# ('.' or ',') and at most two fractional digits. Deliberately strict — it rejects
# scientific notation ('1e3'), digit-group separators ('1_000'), signs, whitespace-embedded
# junk, Unicode/fullwidth digits, and thousands-grouped input ('1,000', '10.000', which have
# three digits after the separator). Those must be re-prompted, never silently reinterpreted
# into a different amount. ``[0-9]`` (not ``\d``) so Unicode digits do not sneak through.
_USER_AMOUNT_RE = re.compile(r"^[0-9]+([.,][0-9]{1,2})?$")

# ISO 4217 minor-unit exponents for the currencies we support.
# USD: 100 cents = 1 dollar. CDF: officially 100 centimes = 1 franc (in everyday
# practice the DRC transacts in whole francs, but we keep the official exponent so
# nothing is silently truncated).
CURRENCY_EXPONENTS: dict[str, int] = {"USD": 2, "CDF": 2}


class CurrencyMismatch(ValueError):
    """Raised when two Money values of different currencies are combined."""


class UnknownCurrency(ValueError):
    """Raised for a currency we do not (yet) support."""


@dataclass(frozen=True)
class Money:
    """An exact monetary amount: integer minor units + ISO-4217 currency."""

    amount_minor: int  # e.g. 1050 == 10.50 USD
    currency: str

    def __post_init__(self) -> None:
        if self.currency not in CURRENCY_EXPONENTS:
            raise UnknownCurrency(self.currency)
        # bool is a subclass of int; reject it and floats explicitly.
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise TypeError("amount_minor must be an int (minor units), never a float")

    # ---- construction -------------------------------------------------
    @classmethod
    def from_major(cls, major: str | int | Decimal, currency: str) -> Money:
        """Parse a human-facing amount ('10.50') into minor units, exactly."""
        if currency not in CURRENCY_EXPONENTS:
            raise UnknownCurrency(currency)
        exponent = CURRENCY_EXPONENTS[currency]
        quantum = Decimal(1).scaleb(-exponent)  # e.g. Decimal('0.01')
        value = Decimal(str(major)).quantize(quantum, rounding=ROUND_HALF_UP)
        minor = int(value.scaleb(exponent).to_integral_value())
        return cls(minor, currency)

    @classmethod
    def from_user_input(cls, text: str, currency: str) -> Money:
        """Parse an amount a human *typed*, strictly. Unlike ``from_major`` (which trusts its
        caller and will happily accept anything ``Decimal`` does — ``'1e3'``, ``'1_000'``,
        fullwidth digits), this accepts only a plain decimal string with an optional ',' or '.'
        separator and 1-2 fractional digits, so ambiguous or exotic input is rejected instead of
        silently becoming a different amount. Accepts the francophone comma decimal ('10,50').
        Raises ``ValueError`` on anything else."""
        cleaned = text.strip()
        if not _USER_AMOUNT_RE.match(cleaned):
            raise ValueError(f"not a plain decimal amount: {text!r}")
        return cls.from_major(cleaned.replace(",", "."), currency)

    # ---- presentation -------------------------------------------------
    def to_major_str(self) -> str:
        """Render as a human-facing decimal string, e.g. '10.50'."""
        exponent = CURRENCY_EXPONENTS[self.currency]
        return str(Decimal(self.amount_minor).scaleb(-exponent))

    # ---- arithmetic (same currency only) ------------------------------
    def _check_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(f"{self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    @property
    def is_positive(self) -> bool:
        return self.amount_minor > 0

    def __str__(self) -> str:
        return f"{self.to_major_str()} {self.currency}"
