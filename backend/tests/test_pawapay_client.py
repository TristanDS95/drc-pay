"""pawaPay client: request shapes, provider prediction, provider-aware amount decimals,
and ack parsing — all against a mocked HTTP transport (no real pawaPay, no network).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.integrations.pawapay.client import PawaPayClient
from drc_pay_api.integrations.pawapay.providers import format_amount, provider_decimals


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
        payout_id="pay-1",
        phone_number="243810000002",
        provider="AIRTEL_COD",
        amount=Money(1000, "USD"),
    )
    assert cap["url"].endswith("/v2/payouts")
    assert cap["body"]["recipient"]["accountDetails"]["provider"] == "AIRTEL_COD"
    assert cap["body"]["amount"] == "10.00"
    assert ack.accepted


def test_refund_request_shape() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(cap, {"refundId": "ref-1", "status": "ACCEPTED"})
    ack = client.request_refund(
        refund_id="ref-1", deposit_id="dep-1", amount=Money(1050, "USD"), provider="ORANGE_COD"
    )
    assert cap["url"].endswith("/v2/refunds")
    assert cap["body"]["refundId"] == "ref-1"
    assert cap["body"]["depositId"] == "dep-1"
    assert ack.accepted


def test_predict_provider() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(
        cap, {"country": "COD", "provider": "VODACOM_MPESA_COD", "phoneNumber": "243800000001"}
    )
    prediction = client.predict_provider("+243 80 000 0001")
    assert cap["url"].endswith("/v2/predict-provider")
    assert cap["body"] == {"phoneNumber": "+243 80 000 0001"}
    assert prediction.provider == "VODACOM_MPESA_COD"
    assert prediction.phone_number == "243800000001"  # pawaPay sanitised it
    assert prediction.country == "COD"


def test_mpesa_cdf_amount_has_no_decimals() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(cap, {"depositId": "d", "status": "ACCEPTED"})
    client.request_deposit(
        deposit_id="d",
        phone_number="243800000001",
        provider="VODACOM_MPESA_COD",
        amount=Money(10000, "CDF"),  # 100.00 CDF
    )
    assert cap["body"]["amount"] == "100"  # Vodacom M-Pesa CDF takes NO decimals
    assert cap["body"]["currency"] == "CDF"


def test_provider_decimals_and_format() -> None:
    assert provider_decimals("VODACOM_MPESA_COD", "CDF") == 0
    assert provider_decimals("AIRTEL_COD", "CDF") == 2
    assert provider_decimals("ORANGE_COD", "USD") == 2
    assert provider_decimals("UNKNOWN", "USD") == 2  # default
    assert format_amount(Money(1050, "USD"), 2) == "10.50"
    assert format_amount(Money(10000, "CDF"), 0) == "100"
    try:
        format_amount(Money(10050, "CDF"), 0)  # 100.50 cannot be 0 decimals
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for impossible precision")


def test_rejected_ack_is_parsed() -> None:
    cap: dict[str, Any] = {}
    client = _client_capturing(
        cap,
        {
            "depositId": "dep-2",
            "status": "REJECTED",
            "failureReason": {
                "failureCode": "INVALID_PHONE_NUMBER",
                "failureMessage": "bad number",
            },
        },
    )
    ack = client.request_deposit(
        deposit_id="dep-2", phone_number="x", provider="ORANGE_COD", amount=Money(100, "USD")
    )
    assert not ack.accepted
    assert ack.status == "REJECTED"
    assert ack.failure_code == "INVALID_PHONE_NUMBER"


def _status_client(
    cap: dict[str, Any], response_json: dict[str, Any], code: int = 200
) -> PawaPayClient:
    def handler(request: httpx.Request) -> httpx.Response:
        cap["method"] = request.method
        cap["url"] = str(request.url)
        return httpx.Response(code, json=response_json)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return PawaPayClient(base_url="https://api.sandbox.pawapay.io", api_token="tkn", http=http)


def test_get_deposit_status_path_and_parse() -> None:
    cap: dict[str, Any] = {}
    client = _status_client(cap, {"depositId": "dep-1", "status": "COMPLETED"})
    status = client.get_deposit_status("dep-1")
    assert cap["method"] == "GET"
    assert cap["url"].endswith("/v2/deposits/dep-1")
    assert status.status == "COMPLETED"


def test_get_payout_and_refund_status_paths() -> None:
    cap: dict[str, Any] = {}
    assert _status_client(cap, {"status": "FAILED"}).get_payout_status("pay-1").status == "FAILED"
    assert cap["url"].endswith("/v2/payouts/pay-1")
    assert (
        _status_client(cap, {"status": "COMPLETED"}).get_refund_status("ref-1").status
        == "COMPLETED"
    )
    assert cap["url"].endswith("/v2/refunds/ref-1")


def test_status_tolerates_data_wrapper() -> None:
    cap: dict[str, Any] = {}
    client = _status_client(cap, {"data": {"depositId": "dep-1", "status": "COMPLETED"}})
    assert client.get_deposit_status("dep-1").status == "COMPLETED"


def test_status_unreadable_is_none() -> None:
    # Fail-safe: a non-2xx response, or a 200 with no status field, yields None (→ treated as
    # still-pending by the sweep — we never invent a terminal outcome).
    cap: dict[str, Any] = {}
    assert (
        _status_client(cap, {"error": "not found"}, code=404).get_deposit_status("x").status is None
    )
    assert _status_client(cap, {"depositId": "dep-1"}).get_deposit_status("dep-1").status is None


def test_get_callback_public_key_prefers_ec_p256() -> None:
    cap: dict[str, Any] = {}
    pem = "-----BEGIN PUBLIC KEY-----\nMFkwEC...\n-----END PUBLIC KEY-----\n"

    def handler(request: httpx.Request) -> httpx.Response:
        cap["method"] = request.method
        cap["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[
                {"id": "HTTP_RSA_KEY:1", "key": "rsa-pem"},
                {"id": "HTTP_EC_P256_KEY:1", "key": pem},
            ],
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = PawaPayClient(base_url="https://api.sandbox.pawapay.io", api_token="tkn", http=http)
    key = client.get_callback_public_key()
    assert cap["method"] == "GET"
    assert cap["url"].endswith("/v2/public-key/http")
    assert key == pem  # the EC P-256 key, not the RSA one


def test_get_callback_public_key_none_on_error() -> None:
    # Fail-safe: a non-2xx (or unreadable) response yields None, so startup never crashes.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "nope"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = PawaPayClient(base_url="https://x", api_token="t", http=http)
    assert client.get_callback_public_key() is None


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_pawapay_client: all passed")
