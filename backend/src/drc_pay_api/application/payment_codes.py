"""A merchant's customer-facing payment codes, built from the USSD shortcode + the
merchant's till.

The customer pays by **dialing** the ``ussd_string`` (``*123*1001#``) on any phone, or by
**scanning a QR** of the ``tel_uri`` (``tel:*123*1001%23``) — the camera then offers to
dial that same USSD string (Android; iOS blocks ``*``/``#`` dialing). Either way the input
lands in the ``ussd/`` channel pre-filled with the till. A static merchant sticker shows
both the QR and the printed ``ussd_string`` so non-scanning phones can dial it manually.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MerchantPaymentCode:
    short_code: str  # "1001"
    ussd_string: str  # "*123*1001#" — human-readable, dialable on any phone
    tel_uri: str  # "tel:*123*1001%23" — the scannable QR payload (offers to dial)


def merchant_payment_code(shortcode: str, short_code: str) -> MerchantPaymentCode:
    base = shortcode.rstrip("#")  # "*123#" -> "*123"
    ussd_string = f"{base}*{short_code}#"  # "*123*1001#"
    tel_uri = "tel:" + ussd_string.replace("#", "%23")  # "tel:*123*1001%23"
    return MerchantPaymentCode(short_code=short_code, ussd_string=ussd_string, tel_uri=tel_uri)
