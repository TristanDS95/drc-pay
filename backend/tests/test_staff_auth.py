"""Staff (admin) authentication — the admin analogue of test_auth, plus the cross-tier
isolation that makes two identities safe: a merchant session is never an admin session, and an
admin session is never a merchant session. Same posture as merchant auth (indistinguishable
failures, opaque expiring sessions), on its own service and its own cookie.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.domains.staff.models import ROLE_ADMIN
from drc_pay_api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def _admin_token(client: TestClient) -> str:
    response = client.post("/admin/login", json={"username": "admin", "password": "admin-demo"})
    assert response.status_code == 200, response.text
    return response.json()["token"]


# ---- authentication ----------------------------------------------------------
def test_admin_login_returns_token_and_principal() -> None:
    response = _client().post("/admin/login", json={"username": "admin", "password": "admin-demo"})
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["admin"]["username"] == "admin"
    assert body["admin"]["role"] == ROLE_ADMIN


def test_admin_login_failures_are_indistinguishable_401s() -> None:
    client = _client()
    wrong_pw = client.post("/admin/login", json={"username": "admin", "password": "nope"})
    unknown = client.post("/admin/login", json={"username": "ghost", "password": "admin-demo"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()  # same body — no user-exists oracle


def test_admin_me_reflects_the_session() -> None:
    client = _client()
    client.headers["Authorization"] = f"Bearer {_admin_token(client)}"
    body = client.get("/admin/me").json()
    assert body["username"] == "admin"
    assert body["role"] == ROLE_ADMIN


def test_admin_logout_revokes_the_session() -> None:
    client = _client()
    client.headers["Authorization"] = f"Bearer {_admin_token(client)}"
    assert client.get("/admin/me").status_code == 200
    assert client.post("/admin/logout").status_code == 200
    assert client.get("/admin/me").status_code == 401  # same token no longer works


def test_admin_me_requires_a_session() -> None:
    assert _client().get("/admin/me").status_code == 401


# ---- cross-tier isolation ----------------------------------------------------
def test_merchant_session_is_not_an_admin_session() -> None:
    client = _client()
    merchant_token = client.post(
        "/auth/login", json={"username": "alpha", "password": "alpha-demo"}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {merchant_token}"
    assert client.get("/admin/me").status_code == 401  # a merchant token can't act as admin


def test_admin_session_is_not_a_merchant_session() -> None:
    client = _client()
    client.headers["Authorization"] = f"Bearer {_admin_token(client)}"
    assert client.get("/auth/me").status_code == 401  # an admin token isn't a merchant
    assert client.get("/transactions").status_code == 401  # ...and can't reach the merchant API
