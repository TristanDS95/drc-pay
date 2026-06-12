"""pawaPay v2 HTTP client — the outbound calls to pawaPay's Merchant API.

The ONLY module that knows pawaPay's wire format. Built to pawaPay's v2 docs (accessed
2026-06): deposits = collections, payouts = disbursements, refunds reverse a deposit,
predict-provider maps a phone number to its operator.

The API is **asynchronous**: financial calls return a synchronous acknowledgement
(``ACCEPTED`` / ``REJECTED`` / ``DUPLICATE_IGNORED``); the FINAL outcome arrives later via
a signed callback handled by the webhook receiver (built separately).

Sources:
  https://docs.pawapay.io/using_the_api                              (base URLs, Bearer auth)
  https://docs.pawapay.io/v2/api-reference/deposits/initiate-deposit
  https://docs.pawapay.io/v2/api-reference/payouts/initiate-payout
  https://docs.pawapay.io/v2/api-reference/refunds/initiate-refund
  https://www.pawapay.io/changelog                                   (predict-provider)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ...domains.ledger.money import Money
from .providers import format_amount, provider_decimals
from .status import PawaPayStatus


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


@dataclass
class ProviderPrediction:
    """pawaPay's guess at the operator a phone number belongs to, plus a sanitised
    number. Accuracy is high but not 100% — callers should allow a manual override."""

    provider: str | None
    phone_number: str | None  # sanitised by pawaPay
    country: str | None


def _ack(response: httpx.Response, id_field: str) -> PawaPayAck:
    data: Any = response.json()
    failure = data.get("failureReason") or {}
    return PawaPayAck(
        status=str(data.get("status", "UNKNOWN")),
        provider_id=data.get(id_field),
        failure_code=failure.get("failureCode"),
        failure_message=failure.get("failureMessage"),
    )


def _status(response: httpx.Response) -> PawaPayStatus:
    """Read an operation's status from a status-endpoint response. **Fail-safe:** any
    response we can't read a status string out of (non-2xx, unexpected shape) yields
    ``None``, which the reconciliation sweep treats as still-pending — we never infer a
    terminal outcome we didn't actually see.

    ⚠️ Provisional shape (Phase E): mirrors the callback object — a JSON object carrying a
    ``status`` — and tolerates a single ``{"data": {...}}`` wrapper. This is the one spot to
    adjust once the real status-endpoint payload is confirmed against the sandbox."""
    if response.status_code >= 400:
        return PawaPayStatus(status=None)
    try:
        data: Any = response.json()
    except ValueError:
        return PawaPayStatus(status=None)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    status = data.get("status") if isinstance(data, dict) else None
    return PawaPayStatus(status=status if isinstance(status, str) else None)


class PawaPayClient:
    """Thin, faithful wrapper over pawaPay's v2 endpoints."""

    def __init__(self, *, base_url: str, api_token: str, http: httpx.Client | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=30.0)
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    def predict_provider(self, phone_number: str) -> ProviderPrediction:
        response = self._http.post(
            f"{self._base}/v2/predict-provider",
            json={"phoneNumber": phone_number},
            headers=self._headers,
        )
        data: Any = response.json()
        return ProviderPrediction(
            provider=data.get("provider"),
            phone_number=data.get("phoneNumber"),
            country=data.get("country"),
        )

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
            "amount": format_amount(amount, provider_decimals(provider, amount.currency)),
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
            "amount": format_amount(amount, provider_decimals(provider, amount.currency)),
            "currency": amount.currency,
        }
        if customer_message is not None:
            body["customerMessage"] = customer_message
        response = self._http.post(f"{self._base}/v2/payouts", json=body, headers=self._headers)
        return _ack(response, "payoutId")

    def request_refund(
        self, *, refund_id: str, deposit_id: str, amount: Money, provider: str
    ) -> PawaPayAck:
        # `provider` is used only to format the amount to the right decimal precision;
        # pawaPay derives the actual provider from the original depositId.
        body: dict[str, Any] = {
            "refundId": refund_id,
            "depositId": deposit_id,
            "amount": format_amount(amount, provider_decimals(provider, amount.currency)),
            "currency": amount.currency,
        }
        response = self._http.post(f"{self._base}/v2/refunds", json=body, headers=self._headers)
        return _ack(response, "refundId")

    # ---- status polling (reconciliation safety net) -------------------
    # GET the current status of an operation by its op-id, to resolve a missed callback.
    # Path follows pawaPay's v2 REST convention (the initiate endpoints' resource + /{id});
    # the exact path + response shape are provisional until the sandbox (Phase E) — see
    # ``_status``. The status strings are the same terminal vocabulary as the callbacks.

    def get_deposit_status(self, deposit_id: str) -> PawaPayStatus:
        response = self._http.get(f"{self._base}/v2/deposits/{deposit_id}", headers=self._headers)
        return _status(response)

    def get_payout_status(self, payout_id: str) -> PawaPayStatus:
        response = self._http.get(f"{self._base}/v2/payouts/{payout_id}", headers=self._headers)
        return _status(response)

    def get_refund_status(self, refund_id: str) -> PawaPayStatus:
        response = self._http.get(f"{self._base}/v2/refunds/{refund_id}", headers=self._headers)
        return _status(response)
