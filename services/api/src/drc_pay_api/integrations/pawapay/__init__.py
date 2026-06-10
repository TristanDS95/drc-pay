"""pawaPay integration boundary.

The ONLY module that knows pawaPay's wire format. Everything else depends on the
``PawaPayClient`` Protocol below, so the real HTTP client and the local
``tooling/pawapay-sim`` fake are interchangeable, and any pawaPay API change is
contained here.

The method shapes below are an illustrative sketch — refine them against pawaPay's
actual API once sandbox access is in hand. Amounts cross this boundary as integer
minor units + currency, matching ``domains.ledger.money.Money``.
"""
from __future__ import annotations

from typing import Protocol


class PawaPayClient(Protocol):
    def request_collection(
        self, *, deposit_id: str, msisdn: str, amount_minor: int, currency: str
    ) -> dict[str, object]: ...

    def request_payout(
        self, *, payout_id: str, msisdn: str, amount_minor: int, currency: str
    ) -> dict[str, object]: ...

    def request_refund(self, *, refund_id: str, deposit_id: str) -> dict[str, object]: ...

    def get_status(self, *, kind: str, object_id: str) -> dict[str, object]: ...
