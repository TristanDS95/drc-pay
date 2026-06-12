"""pawaPay provider codes and amount rules for the DRC.

Verified from pawaPay's v2 docs (accessed 2026-06-11):
  providers:   https://docs.pawapay.io/v2/docs/providers
  active-conf: https://docs.pawapay.io/v2/api-reference/toolkit/active-configuration

Operator detection (phone number -> provider) is handled by pawaPay's predict-provider
endpoint (see ``client.PawaPayClient.predict_provider``), not by us.
"""
from __future__ import annotations

from decimal import Decimal

from ...domains.ledger.money import CURRENCY_EXPONENTS, Money

# DRC pawaPay provider codes are used as plain strings (matching pawaPay's wire format and
# predict-provider output): VODACOM_MPESA_COD, AIRTEL_COD, ORANGE_COD.

# Decimal places pawaPay accepts per (provider, currency). Verified from the v2 providers
# page. The authoritative LIVE source is GET /v2/active-conf (``decimalsInAmount``); this
# static map is a stopgap for the three DRC providers until we consume active-conf.
_DECIMALS: dict[tuple[str, str], int] = {
    ("VODACOM_MPESA_COD", "CDF"): 0,  # Vodacom M-Pesa CDF takes NO decimals
    ("VODACOM_MPESA_COD", "USD"): 2,
    ("AIRTEL_COD", "CDF"): 2,
    ("AIRTEL_COD", "USD"): 2,
    ("ORANGE_COD", "CDF"): 2,
    ("ORANGE_COD", "USD"): 2,
}


def provider_decimals(provider: str, currency: str) -> int:
    """Decimal places this provider accepts for this currency (default 2)."""
    return _DECIMALS.get((provider, currency), 2)


def format_amount(amount: Money, decimals: int) -> str:
    """Render an amount as a pawaPay amount string with exactly ``decimals`` places.

    Raises ``ValueError`` if the amount has finer precision than the provider allows —
    we never silently round money.
    """
    major = Decimal(amount.amount_minor).scaleb(-CURRENCY_EXPONENTS[amount.currency])
    quantum = Decimal(1).scaleb(-decimals)
    rendered = major.quantize(quantum)
    if rendered != major:
        raise ValueError(
            f"{major} {amount.currency} cannot be represented in {decimals} decimal places"
        )
    return str(rendered)
