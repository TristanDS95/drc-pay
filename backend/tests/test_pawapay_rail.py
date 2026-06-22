"""PawaPayRail: it adapts the client to the PaymentRail port — generating op-ids,
issuing the right call, returning the op-id, and failing loudly on a non-ACCEPTED ack.
All against a mocked HTTP transport (no real pawaPay, no network).
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.integrations.pawapay.client import PawaPayClient
from drc_pay_api.integrations.pawapay.rail import PawaPayRail, PawaPayRailError


def _rail_capturing(into: dict[str, Any], response_json: dict[str, Any]) -> PawaPayRail:
    def handler(request: httpx.Request) -> httpx.Response:
        into["url"] = str(request.url)
        into["body"] = json.loads(request.content)
        return httpx.Response(200, json=response_json)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = PawaPayClient(base_url="https://api.sandbox.pawapay.io", api_token="tkn", http=http)
    return PawaPayRail(client)


def test_collection_issues_deposit_and_returns_op_id() -> None:
    cap: dict[str, Any] = {}
    rail = _rail_capturing(cap, {"status": "ACCEPTED"})
    op_id = rail.request_collection(
        transaction_id="t1", msisdn="243800000001", amount=Money(1050, "USD"), provider="ORANGE_COD"
    )
    assert cap["url"].endswith("/v2/deposits")
    assert op_id is not None
    assert cap["body"]["depositId"] == op_id  # we generate the id and send it
    assert cap["body"]["amount"] == "10.50"
    assert cap["body"]["payer"]["accountDetails"]["provider"] == "ORANGE_COD"


def test_payout_issues_payout_and_returns_op_id() -> None:
    cap: dict[str, Any] = {}
    rail = _rail_capturing(cap, {"status": "ACCEPTED"})
    op_id = rail.request_payout(
        transaction_id="t1", msisdn="243810000002", amount=Money(1000, "USD"), provider="AIRTEL_COD"
    )
    assert cap["url"].endswith("/v2/payouts")
    assert cap["body"]["payoutId"] == op_id
    assert cap["body"]["recipient"]["accountDetails"]["provider"] == "AIRTEL_COD"


def test_refund_references_the_original_deposit() -> None:
    cap: dict[str, Any] = {}
    rail = _rail_capturing(cap, {"status": "ACCEPTED"})
    op_id = rail.request_refund(
        transaction_id="t1", deposit_id="dep-123", amount=Money(1050, "USD"), provider="ORANGE_COD"
    )
    assert cap["url"].endswith("/v2/refunds")
    assert cap["body"]["depositId"] == "dep-123"  # threaded through from the collection leg
    assert cap["body"]["refundId"] == op_id


def test_rejected_ack_raises() -> None:
    cap: dict[str, Any] = {}
    rail = _rail_capturing(
        cap,
        {
            "status": "REJECTED",
            "failureReason": {"failureCode": "INVALID_PHONE_NUMBER", "failureMessage": "bad number"},
        },
    )
    try:
        rail.request_collection(
            transaction_id="t1", msisdn="x", amount=Money(100, "USD"), provider="ORANGE_COD"
        )
    except PawaPayRailError as exc:
        assert "bad number" in str(exc)
        assert exc.ack is not None and exc.ack.status == "REJECTED"
    else:
        raise AssertionError("expected PawaPayRailError on a rejected ack")


def test_refund_without_deposit_id_raises() -> None:
    rail = _rail_capturing({}, {"status": "ACCEPTED"})
    try:
        rail.request_refund(
            transaction_id="t1", deposit_id=None, amount=Money(100, "USD"), provider="ORANGE_COD"
        )
    except PawaPayRailError:
        pass
    else:
        raise AssertionError("expected PawaPayRailError when the original depositId is missing")


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_pawapay_rail: all passed")
