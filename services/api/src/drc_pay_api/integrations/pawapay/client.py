"""pawaPay v2 HTTP client — the outbound calls to pawaPay's Merchant API.

The ONLY module that knows pawaPay's wire format. Built to pawaPay's v2 docs (accessed
2026-06): deposits = collections, payouts = disbursements, refunds reverse a deposit.

The API is **asynchronous**: these calls return a synchronous acknowledgement
(``ACCEPTED`` / ``REJECTED`` / ``DUPLICATE_IGNORED``); the FINAL outcome arrives later via
a signed callback handled by the webhook receiver (built separately).

Sources:
  https://docs.pawapay.io/using_the_api                              (base URLs, Bearer auth)
  https://docs.pawapay.io/v2/api-reference/deposits/initiate-deposit
  https://docs.pawapay.io/v2/api-reference/payouts/initiate-payout
  https://docs.pawapay.io/v2/api-reference/refunds/initiate-refund
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ...domains.ledger.money import Money


@dataclass
class PawaPayAck:
    """pawaPay's synchronous acknowledgement of a financial request."""

    status: str  # ACCEPTED | REJECTED | DUPLICATE_IGNORED
    provider_id: str | None  # the depositId / payoutId / refundId echoed back
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "ACCEPTED"


def _ack(response: httpx.Response, id_field: str) -> PawaPayAck:
    data: Any = response.json()
    failure = data.get("failureReason") or {}
    return PawaPayAck(
        status=str(data.get("status", "UNKNOWN")),
        provider_id=data.get(id_field),
        failure_code=failure.get("failureCode"),
        failure_message=failure.get("failureMessage"),
    )


class PawaPayClient:
    """Thin, faithful wrapper over pawaPay's v2 financial endpoints."""

    def __init__(self, *, base_url: str, api_token: str, http: httpx.Client | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=30.0)
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    def request_deposit(
        self,
        *,
        deposit_id: str,
        phone_number: str,
        provider: str,
        amount: Money,
        customer_message: str | None = None,
    ) -> PawaPayAck:
        body: dict[str, Any] = {
            "depositId": deposit_id,
            "payer": {
                "type": "MMO",
                "accountDetails": {"phoneNumber": phone_number, "provider": provider},
            },
            "amount": amount.to_major_str(),
            "currency": amount.currency,
        }
        if customer_message is not None:
            body["customerMessage"] = customer_message
        response = self._http.post(f"{self._base}/v2/deposits", json=body, headers=self._headers)
        return _ack(response, "depositId")

    def request_payout(
        self,
        *,
        payout_id: str,
        phone_number: str,
        provider: str,
        amount: Money,
        customer_message: str | None = None,
    ) -> PawaPayAck:
        body: dict[str, Any] = {
            "payoutId": payout_id,
            "recipient": {
                "type": "MMO",
                "accountDetails": {"phoneNumber": phone_number, "provider": provider},
            },
            "amount": amount.to_major_str(),
            "currency": amount.currency,
        }
        if customer_message is not None:
            body["customerMessage"] = customer_message
        response = self._http.post(f"{self._base}/v2/payouts", json=body, headers=self._headers)
        return _ack(response, "payoutId")

    def request_refund(self, *, refund_id: str, deposit_id: str, amount: Money) -> PawaPayAck:
        body: dict[str, Any] = {
            "refundId": refund_id,
            "depositId": deposit_id,
            "amount": amount.to_major_str(),
            "currency": amount.currency,
        }
        response = self._http.post(f"{self._base}/v2/refunds", json=body, headers=self._headers)
        return _ack(response, "refundId")
