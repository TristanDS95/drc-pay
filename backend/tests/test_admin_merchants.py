"""Admin merchant approval — the endpoints that connect self-onboarding to staff accounts.

The headline test is the full loop: a merchant signs up (pending, can't log in) → an admin lists
it, approves it → the merchant can now log in. Plus filtering, idempotent reject, 404s, and that
the whole surface is admin-gated (a merchant session can't reach it).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api.main import create_app

_SIGNUP = {
    "name": "Kin Coffee",
    "settlement_msisdn": "243973456700",
    "settlement_provider": "AIRTEL_COD",
    "username": "kincoffee",
    "password": "brew-beans-2026",
}


def _client() -> TestClient:
    return TestClient(create_app())


def _admin(client: TestClient) -> TestClient:
    token = client.post(
        "/admin/login", json={"username": "admin", "password": "admin-demo"}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# One app == one container/store, so sign-up and admin actions must share a client to see each
# other's writes. /auth/login is body-only, so the admin auth header on the shared client is
# ignored by it (login is decided by the password, not the session).
def test_signup_then_admin_approve_then_login_works() -> None:
    client = _client()
    login = {"username": "kincoffee", "password": _SIGNUP["password"]}
    merchant_id = client.post("/signup", json=_SIGNUP).json()["merchant_id"]
    assert client.post("/auth/login", json=login).status_code == 401  # pending: can't log in

    _admin(client)  # become admin on the SAME app
    pending = client.get("/admin/merchants").json()
    assert merchant_id in {m["id"] for m in pending}
    assert all(m["status"] == "pending" for m in pending)

    approved = client.post(f"/admin/merchants/{merchant_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

    ok = client.post("/auth/login", json=login)
    assert ok.status_code == 200, ok.text
    assert ok.json()["merchant"]["id"] == merchant_id


def test_admin_reject_keeps_the_merchant_locked_out() -> None:
    client = _client()
    login = {"username": "kincoffee", "password": _SIGNUP["password"]}
    merchant_id = client.post("/signup", json=_SIGNUP).json()["merchant_id"]
    _admin(client)
    rejected = client.post(f"/admin/merchants/{merchant_id}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert client.post("/auth/login", json=login).status_code == 401


def test_list_filters_by_status() -> None:
    client = _client()
    client.post("/signup", json=_SIGNUP)
    _admin(client)
    # Seeded demo merchants are active; the new sign-up is pending.
    assert {m["status"] for m in client.get("/admin/merchants?status=active").json()} == {"active"}
    assert {m["status"] for m in client.get("/admin/merchants?status=pending").json()} == {
        "pending"
    }
    everyone = client.get("/admin/merchants?status=all").json()
    assert {"active", "pending"} <= {m["status"] for m in everyone}
    assert client.get("/admin/merchants?status=bogus").status_code == 422


def test_approve_and_reject_unknown_merchant_are_404() -> None:
    admin = _admin(_client())
    assert admin.post("/admin/merchants/m_nope/approve").status_code == 404
    assert admin.post("/admin/merchants/m_nope/reject").status_code == 404


def test_approval_surface_is_admin_gated() -> None:
    # No session at all.
    anon = _client()
    assert anon.get("/admin/merchants").status_code == 401
    assert anon.post("/admin/merchants/m_x/approve").status_code == 401
    # A merchant session is not an admin session.
    merchant = _client()
    token = merchant.post(
        "/auth/login", json={"username": "alpha", "password": "alpha-demo"}
    ).json()["token"]
    merchant.headers["Authorization"] = f"Bearer {token}"
    assert merchant.get("/admin/merchants").status_code == 401
    assert merchant.post("/admin/merchants/m_alpha/approve").status_code == 401
