"""Merchant endpoints: the customer-facing payment codes (USSD string / tel URI). Uses the seeded
demo merchants (m_alpha till 1001, m_beta till 1002).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.application.payment_codes import merchant_payment_code
from drc_pay_api.main import create_app

from conftest import as_merchant


def _client() -> TestClient:
    # Logged in as the demo merchant "alpha" (m_alpha) — the merchant API is session-gated.
    return as_merchant(TestClient(create_app()))


def test_payment_code_builds_ussd_and_tel_uri() -> None:
    code = merchant_payment_code("*123#", "1001")
    assert code.ussd_string == "*123*1001#"
    assert code.tel_uri == "tel:*123*1001%23"  # '#' percent-encoded for the QR/dialer


def test_list_merchants_is_scoped_to_the_caller() -> None:
    # One trust tier, one merchant: the list is exactly the logged-in merchant.
    body = _client().get("/merchants").json()
    assert [m["id"] for m in body] == ["m_alpha"]
    assert body[0]["ussd_string"] == "*123*1001#"
    assert body[0]["tel_uri"] == "tel:*123*1001%23"
    beta = as_merchant(TestClient(create_app()), "beta").get("/merchants").json()
    assert [m["id"] for m in beta] == ["m_beta"]
    assert beta[0]["ussd_string"] == "*123*1002#"


def test_get_merchant() -> None:
    body = _client().get("/merchants/m_alpha").json()
    assert body["name"] == "Alpha Gas Station"
    assert body["ussd_string"] == "*123*1001#"


def test_get_unknown_merchant_404() -> None:
    assert _client().get("/merchants/nope").status_code == 404


def test_get_other_merchant_is_404_too() -> None:
    # Cross-merchant reads 404 (not 403) so responses don't confirm the id exists.
    assert _client().get("/merchants/m_beta").status_code == 404


def test_merchant_ussd_qr_svg() -> None:
    # The printable static-till USSD sticker (encodes the tel: dial-through).
    qr = _client().get("/merchants/m_alpha/qr.svg")
    assert qr.status_code == 200
    assert "image/svg" in qr.headers["content-type"]
    assert qr.content.startswith(b"<?xml") or qr.content.lstrip().startswith(b"<svg")


def test_merchant_ussd_qr_unknown_404() -> None:
    assert _client().get("/merchants/nope/qr.svg").status_code == 404


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_merchants: all passed")
