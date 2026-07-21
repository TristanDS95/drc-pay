"""Merchant self-onboarding (phase 1) — sign-up creates a PENDING merchant that cannot log in
or transact until an admin approves it.

Covers the public ``POST /signup`` endpoint, its input validation, the login gate (a correct
password is not enough while pending/rejected), and the approve/reject moves. No money moves
here, so there is no ledger/state-machine coverage — only the merchant + credential stores.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from drc_pay_api.adapters.memory import InMemoryCredentialStore, InMemorySessionStore
from drc_pay_api.application import onboarding
from drc_pay_api.domains.auth.models import MerchantCredential
from drc_pay_api.domains.auth.service import AuthService, hash_password
from drc_pay_api.domains.merchants.models import STATUS_ACTIVE, STATUS_PENDING
from drc_pay_api.main import create_app

_SIGNUP = {
    "name": "New Merchant Ltd",
    "settlement_msisdn": "243973456700",
    "settlement_provider": "AIRTEL_COD",
    "operator_till": "509999",
    "username": "newmerchant",
    "password": "s3cret-pw-1234",
}


def _app() -> tuple[object, TestClient]:
    app = create_app()
    return app, TestClient(app)


# ---- sign-up creates a pending, inert merchant -------------------------------
def test_signup_creates_a_pending_merchant() -> None:
    app, client = _app()
    response = client.post("/signup", json=_SIGNUP)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == STATUS_PENDING
    merchant = app.state.container.merchants.get(body["merchant_id"])  # type: ignore[attr-defined]
    assert merchant.status == STATUS_PENDING
    assert not merchant.is_active  # inert: is_active already fences take-payment / create-charge
    assert merchant.short_code not in {"1001", "1002", "1003"}  # fresh, not a seeded code
    creds = app.state.container.credentials  # type: ignore[attr-defined]
    assert creds.get_by_username("newmerchant") is not None


def test_pending_merchant_cannot_log_in() -> None:
    _, client = _app()
    client.post("/signup", json=_SIGNUP)
    response = client.post(
        "/auth/login", json={"username": "newmerchant", "password": _SIGNUP["password"]}
    )
    assert response.status_code == 401  # correct password, but not approved yet


def test_approve_lets_the_merchant_log_in() -> None:
    app, client = _app()
    merchant_id = client.post("/signup", json=_SIGNUP).json()["merchant_id"]
    onboarding.approve(app.state.container.merchants, merchant_id)  # type: ignore[attr-defined]
    response = client.post(
        "/auth/login", json={"username": "newmerchant", "password": _SIGNUP["password"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["merchant"]["id"] == merchant_id
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    assert client.get("/auth/me").json()["status"] == STATUS_ACTIVE


def test_rejected_merchant_stays_locked_out() -> None:
    app, client = _app()
    merchant_id = client.post("/signup", json=_SIGNUP).json()["merchant_id"]
    onboarding.reject(app.state.container.merchants, merchant_id)  # type: ignore[attr-defined]
    response = client.post(
        "/auth/login", json={"username": "newmerchant", "password": _SIGNUP["password"]}
    )
    assert response.status_code == 401


# ---- uniqueness --------------------------------------------------------------
def test_duplicate_username_is_rejected() -> None:
    _, client = _app()
    assert client.post("/signup", json=_SIGNUP).status_code == 201
    duplicate = dict(_SIGNUP, settlement_msisdn="243973456701")
    assert client.post("/signup", json=duplicate).status_code == 409


def test_signup_generates_unique_short_codes_above_the_seeded_max() -> None:
    app, client = _app()
    first = client.post("/signup", json=dict(_SIGNUP, username="mone")).json()["merchant_id"]
    second = client.post(
        "/signup", json=dict(_SIGNUP, username="mtwo", settlement_msisdn="243973456702")
    ).json()["merchant_id"]
    store = app.state.container.merchants  # type: ignore[attr-defined]
    code_one, code_two = store.get(first).short_code, store.get(second).short_code
    assert code_one != code_two
    assert int(code_one) > 1003 and int(code_two) > 1003  # past the seeded 1001–1003


# ---- input validation --------------------------------------------------------
@pytest.mark.parametrize(
    "override",
    [
        {"settlement_msisdn": "12345"},  # not a DRC number
        {"settlement_msisdn": "243973"},  # too short
        {"password": "short"},  # < 8 chars
        {"username": "ab"},  # too short
        {"username": "has space"},  # invalid characters
        {"settlement_provider": "BOGUS_COD"},  # unknown provider
        {"operator_till": "abc"},  # non-numeric till
        {"name": ""},  # empty name
    ],
)
def test_signup_validation_rejects_bad_input(override: dict[str, str]) -> None:
    _, client = _app()
    response = client.post("/signup", json=dict(_SIGNUP, **override))
    assert response.status_code == 422, f"expected 422 for {override}, got {response.status_code}"


def test_signup_accepts_a_plus_prefixed_number_and_no_provider() -> None:
    _, client = _app()
    body = dict(_SIGNUP, settlement_msisdn="+243973456799", settlement_provider=None)
    assert client.post("/signup", json=body).status_code == 201


# ---- the login gate at the service level (focused) ---------------------------
def _auth_with_active(active: bool) -> AuthService:
    credentials = InMemoryCredentialStore()
    credentials.save(
        MerchantCredential(
            merchant_id="m_x", username="u", password_hash=hash_password("pw-12345678")
        )
    )
    return AuthService(credentials, InMemorySessionStore(), is_merchant_active=lambda _id: active)


def test_login_gate_denies_inactive_merchant() -> None:
    assert _auth_with_active(active=False).login("u", "pw-12345678") is None


def test_login_gate_allows_active_merchant() -> None:
    assert _auth_with_active(active=True).login("u", "pw-12345678") is not None
