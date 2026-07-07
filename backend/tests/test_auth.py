"""Merchant authentication + per-merchant authorization (security roadmap, Gate A).

Two halves, tested together because they only work together:
- **Authentication**: login/logout/me — Argon2id-verified passwords, opaque expiring
  sessions, indistinguishable failures, a login throttle.
- **Authorization**: every merchant endpoint is fenced to the session's merchant —
  merchant A can never read, confirm, or charge as merchant B.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from drc_pay_api.domains.auth.service import AuthService, hash_password
from drc_pay_api.adapters.memory import InMemoryCredentialStore, InMemorySessionStore
from drc_pay_api.domains.auth.models import MerchantCredential
from drc_pay_api.main import create_app

from conftest import as_merchant


def _client() -> TestClient:
    return TestClient(create_app())


# ---- authentication ----------------------------------------------------------
def test_login_returns_token_and_merchant() -> None:
    response = _client().post("/auth/login", json={"username": "alpha", "password": "alpha-demo"})
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["merchant"]["id"] == "m_alpha"
    assert body["merchant"]["name"] == "Alpha Gas Station"


def test_login_failures_are_indistinguishable_401s() -> None:
    client = _client()
    wrong_pw = client.post("/auth/login", json={"username": "alpha", "password": "nope"})
    unknown = client.post("/auth/login", json={"username": "who", "password": "alpha-demo"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()  # same body — no user-exists oracle


def test_me_reflects_the_session() -> None:
    client = as_merchant(_client(), "beta")
    assert client.get("/auth/me").json()["id"] == "m_beta"


def test_logout_revokes_the_session() -> None:
    client = as_merchant(_client())
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401  # same token no longer works


def test_x_session_token_is_the_primary_carrier() -> None:
    # The console sends the session in X-Session-Token because Safari REPLACES custom
    # Authorization headers with the cached Basic credentials of the sandbox demo gate.
    client = _client()
    token = client.post(
        "/auth/login", json={"username": "gamma", "password": "gamma-demo"}
    ).json()["token"]
    assert client.get("/auth/me", headers={"X-Session-Token": token}).status_code == 200
    # The Safari situation itself: our header present AND a Basic Authorization header
    # injected by the browser. The session must still resolve.
    safari = {"X-Session-Token": token, "Authorization": "Basic ZHJjcGF5OnNlc2FtZQ=="}
    me = client.get("/auth/me", headers=safari)
    assert me.status_code == 200 and me.json()["id"] == "m_gamma"
    assert client.get("/transactions", headers=safari).status_code == 200
    # Logout works through the same carrier and actually revokes.
    assert client.post("/auth/logout", headers=safari).status_code == 200
    assert client.get("/auth/me", headers=safari).status_code == 401


def test_garbage_and_missing_tokens_are_401() -> None:
    client = _client()
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Basic junk"}).status_code == 401


def test_sessions_expire() -> None:
    credentials = InMemoryCredentialStore()
    credentials.save(
        MerchantCredential(merchant_id="m_x", username="x", password_hash=hash_password("pw"))
    )
    sessions = InMemorySessionStore()
    service = AuthService(credentials, sessions)
    token = service.login("x", "pw")
    assert token is not None
    assert service.resolve(token) == "m_x"
    # Age the session past its TTL, then it resolves to nothing and is purged.
    session = next(iter(sessions._rows.values()))
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert service.resolve(token) is None
    assert sessions.get(session.token_hash) is None  # lazily deleted


def test_login_throttle_locks_after_repeated_failures() -> None:
    credentials = InMemoryCredentialStore()
    credentials.save(
        MerchantCredential(merchant_id="m_x", username="x", password_hash=hash_password("pw"))
    )
    service = AuthService(credentials, InMemorySessionStore())
    for _ in range(5):
        assert service.login("x", "wrong") is None
    # Locked: even the CORRECT password is refused while the lockout stands.
    assert service.login("x", "pw") is None


def test_passwords_and_tokens_are_never_stored_in_plaintext() -> None:
    credentials = InMemoryCredentialStore()
    credentials.save(
        MerchantCredential(merchant_id="m_x", username="x", password_hash=hash_password("pw"))
    )
    sessions = InMemorySessionStore()
    service = AuthService(credentials, sessions)
    token = service.login("x", "pw")
    assert token is not None
    stored_credential = credentials.get_by_username("x")
    assert stored_credential is not None and "pw" not in stored_credential.password_hash
    assert stored_credential.password_hash.startswith("$argon2id$")
    assert token not in sessions._rows  # keyed by hash, not by the token itself


# ---- per-merchant authorization ------------------------------------------------
def _pay_as(client: TestClient, msisdn: str = "243800000001") -> str:
    tx = client.post(
        "/transactions", json={"customer_msisdn": msisdn, "amount": "10.00"}
    ).json()
    tx_id: str = tx["id"]
    return tx_id


def test_merchants_cannot_see_each_others_transactions() -> None:
    app_client = _client()
    alpha = as_merchant(app_client)
    tx_id = _pay_as(alpha)
    assert alpha.get(f"/transactions/{tx_id}").status_code == 200

    beta = as_merchant(TestClient(app_client.app), "beta")  # same app/container, other merchant
    assert beta.get(f"/transactions/{tx_id}").status_code == 404  # 404, not 403 — no id oracle
    assert beta.get("/transactions").json() == []


def test_merchants_cannot_confirm_each_others_on_net_payments() -> None:
    app_client = _client()
    gamma = as_merchant(app_client, "gamma")
    # Vodacom payer → Vodacom merchant (gamma) = on-net, lands awaiting merchant confirmation.
    tx = gamma.post(
        "/transactions", json={"customer_msisdn": "243813456789", "amount": "8.00"}
    ).json()
    assert tx["provenance"] == "merchant_attested"

    beta = as_merchant(TestClient(app_client.app), "beta")
    stolen = beta.post(f"/transactions/{tx['id']}/confirm")
    assert stolen.status_code == 404  # only the OWNING merchant's word marks money received

    assert gamma.post(f"/transactions/{tx['id']}/confirm").status_code == 200
    assert gamma.get(f"/transactions/{tx['id']}").json()["state"] == "payout_succeeded"


def test_merchants_cannot_see_each_others_charges() -> None:
    app_client = _client()
    alpha = as_merchant(app_client)
    charge = alpha.post("/charges", json={"amount": "12.50"}).json()
    assert charge["merchant_id"] == "m_alpha"  # from the session, no body merchant_id needed

    beta = as_merchant(TestClient(app_client.app), "beta")
    assert beta.get(f"/charges/{charge['id']}").status_code == 404
    assert beta.post(
        "/charges", json={"merchant_id": "m_alpha", "amount": "1.00"}
    ).status_code == 403  # cannot charge as someone else


def test_charge_qr_is_public_by_design() -> None:
    # <img> tags can't send Authorization headers, and a QR exists to be scanned — the SVG
    # endpoints are deliberately session-exempt (their content is public pay info).
    client = as_merchant(_client())
    charge = client.post("/charges", json={"amount": "5.00"}).json()
    anonymous = TestClient(client.app)
    assert anonymous.get(f"/charges/{charge['id']}/qr.svg").status_code == 200
    assert anonymous.get("/merchants/m_alpha/qr.svg").status_code == 200


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_auth: all passed")
