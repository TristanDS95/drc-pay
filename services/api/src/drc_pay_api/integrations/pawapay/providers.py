"""pawaPay provider codes for the DRC.

Verified from pawaPay's v2 provider list (accessed 2026-06):
https://docs.pawapay.io/v2/docs/providers

NOTE: resolving a phone number to its provider (operator detection) is a SEPARATE,
not-yet-built concern. Options to decide on: pawaPay's availability/prediction
capability, a number-prefix lookup, or letting the user pick the network. Until then,
the provider must be supplied explicitly to the client.
"""
from __future__ import annotations

from enum import Enum


class DrcProvider(str, Enum):
    VODACOM_MPESA = "VODACOM_MPESA_COD"
    AIRTEL = "AIRTEL_COD"
    ORANGE = "ORANGE_COD"
