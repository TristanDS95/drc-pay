"""pawaPay client: request shapes + acknowledgement parsing, against a mocked HTTP
transport — verifies we build the documented requests and parse responses, with no real
pawaPay and no network.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.integrations.pawapay.client import PawaPayClient


def _client_capturing(into: dict[str, Any], response_json: dict[str, Any]) -> PawaPayClient:
    def handler(request: httpx.Request) -> httpx.Response:
        into["method"] = request.method
        into["url"] = str(request.url)
        into["authorization"] = request.headers.get("authorization")
        into["body"] = json.loads(request.content)
        return httpx.Response(200, json=response_json)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return PawaPayClient(base_url="https://api.sandbox.pawapay.io", api_token="tkn", http=http)


def test_deposit_request_shape_and_ack() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(cap, {"depositId": "dep-1", "status": "ACCEPTED"})
    ack = client.request_deposit(
        deposit_id="dep-1",
        phone_number="243800000001",
        provider="VODACOM_MPESA_COD",
        amount=Money(1050, "USD"),
    )
    assert cap["method"] == "POST"
    assert cap["url"].endswith("/v2/deposits")
    assert cap["authorization"] == "Bearer tkn"
    assert cap["body"]["depositId"] == "dep-1"
    assert cap["body"]["payer"]["accountDetails"]["provider"] == "VODACOM_MPESA_COD"
    assert cap["body"]["amount"] == "10.50"
    assert cap["body"]["currency"] == "USD"
    assert ack.accepted
    assert ack.provider_id == "dep-1"


def test_payout_request_shape() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(cap, {"payoutId": "pay-1", "status": "ACCEPTED"})
    ack = client.request_payout(
        payout_id="pay-1", phone_number="243810000002", provider="AIRTEL_COD", amount=Money(1000, "USD")
    )
    assert cap["url"].endswith("/v2/payouts")
    assert cap["body"]["recipient"]["accountDetails"]["provider"] == "AIRTEL_COD"
    assert cap["body"]["amount"] == "10.00"
    assert ack.accepted


def test_refund_request_shape() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(cap, {"refundId": "ref-1", "status": "ACCEPTED"})
    ack = client.request_refund(refund_id="ref-1", deposit_id="dep-1", amount=Money(1050, "USD"))
    assert cap["url"].endswith("/v2/refunds")
    assert cap["body"]["refundId"] == "ref-1"
    assert cap["body"]["depositId"] == "dep-1"
    assert ack.accepted


def test_rejected_ack_is_parsed() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(
        cap,
        {
            "depositId": "dep-2",
            "status": "REJECTED",
            "failureReason": {"failureCode": "INVALID_PHONE_NUMBER", "failureMessage": "bad number"},
        },
    )
    ack = client.request_deposit(
        deposit_id="dep-2", phone_number="x", provider="ORANGE_COD", amount=Money(100, "USD")
    )
    assert not ack.accepted
    assert ack.status == "REJECTED"
    assert ack.failure_code == "INVALID_PHONE_NUMBER"


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_pawapay_client: all passed")
