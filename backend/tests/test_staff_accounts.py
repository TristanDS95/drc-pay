"""Creating staff accounts — the three paths that can mint an admin.

1. **Bootstrap** (``DRCPAY_ADMIN_USERNAME``/``_PASSWORD``): the only way a *production* deploy,
   which seeds nothing else, gets a staff account. Must be idempotent so a redeploy rotates the
   password instead of piling up duplicates.
2. **CLI** (``python -m drc_pay_api.create_staff``): same upsert semantics, ad hoc.
3. **Admin endpoint** (an admin adding a colleague): deliberately create-ONLY — a taken username
   must 409, never silently reset an existing admin's password.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from drc_pay_api.adapters.memory import InMemoryStaffCredentialStore
from drc_pay_api.application import staff_accounts
from drc_pay_api.domains.staff.models import ROLE_ADMIN
from drc_pay_api.main import create_app
from drc_pay_api.seed import ensure_bootstrap_admin


def _client() -> TestClient:
    return TestClient(create_app())


def _as_admin(client: TestClient) -> TestClient:
    token = client.post(
        "/admin/login", json={"username": "admin", "password": "admin-demo"}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ---- 1. bootstrap -------------------------------------------------------------
def test_bootstrap_creates_an_admin_and_is_idempotent() -> None:
    store = InMemoryStaffCredentialStore()
    assert ensure_bootstrap_admin(store, "ops", "bootstrap-pw-1") == "ops"
    first = store.get_by_username("ops")
    assert first is not None and first.role == ROLE_ADMIN

    # A redeploy with a ROTATED password updates the SAME account (same staff_id), so sessions
    # and any future foreign keys stay pointed at one row instead of a duplicate.
    assert ensure_bootstrap_admin(store, "ops", "bootstrap-pw-2") == "ops"
    second = store.get_by_username("ops")
    assert second is not None
    assert second.staff_id == first.staff_id
    assert second.password_hash != first.password_hash  # rotation actually took effect
    assert len(store.all()) == 1


def test_bootstrap_is_a_noop_when_unconfigured() -> None:
    store = InMemoryStaffCredentialStore()
    assert ensure_bootstrap_admin(store, "", "") is None
    assert ensure_bootstrap_admin(store, "ops", "") is None  # half-configured counts as unset
    assert ensure_bootstrap_admin(store, "", "pw-12345678") is None
    assert store.all() == []


def test_bootstrap_rejects_an_unusable_password() -> None:
    # Failing the deploy loudly beats booting with an admin nobody can log into.
    with pytest.raises(staff_accounts.InvalidStaffAccount):
        ensure_bootstrap_admin(InMemoryStaffCredentialStore(), "ops", "short")


# ---- 2. shared create/upsert semantics ---------------------------------------
def test_create_staff_refuses_an_existing_username() -> None:
    store = InMemoryStaffCredentialStore()
    staff_accounts.create_staff(store, username="alice", password="alice-pw-123")
    with pytest.raises(staff_accounts.StaffUsernameTaken):
        staff_accounts.create_staff(store, username="alice", password="different-pw-9")
    # ...and the original password was NOT overwritten by the failed attempt.
    assert len(store.all()) == 1


@pytest.mark.parametrize(
    "username,password,role",
    [
        ("ab", "good-password-1", ROLE_ADMIN),  # username too short
        ("has space", "good-password-1", ROLE_ADMIN),  # invalid characters
        ("alice", "short", ROLE_ADMIN),  # password too short
        ("alice", "good-password-1", "superuser"),  # unknown role
    ],
)
def test_validation_rejects_bad_accounts(username: str, password: str, role: str) -> None:
    with pytest.raises(staff_accounts.InvalidStaffAccount):
        staff_accounts.create_staff(
            InMemoryStaffCredentialStore(), username=username, password=password, role=role
        )


# ---- 3. the admin endpoint ----------------------------------------------------
def test_admin_can_create_a_colleague_who_can_then_log_in() -> None:
    client = _as_admin(_client())
    created = client.post("/admin/staff", json={"username": "alice", "password": "alice-pw-123"})
    assert created.status_code == 201, created.text
    assert created.json()["username"] == "alice"
    assert created.json()["role"] == ROLE_ADMIN

    # The new account is real: it can sign in on its own and reach the admin surface.
    fresh = TestClient(client.app)  # same app/container, no inherited auth header
    login = fresh.post("/admin/login", json={"username": "alice", "password": "alice-pw-123"})
    assert login.status_code == 200
    fresh.headers["Authorization"] = f"Bearer {login.json()['token']}"
    assert fresh.get("/admin/merchants").status_code == 200


def test_creating_a_duplicate_username_is_409_not_a_password_reset() -> None:
    client = _as_admin(_client())
    assert (
        client.post(
            "/admin/staff", json={"username": "alice", "password": "alice-pw-123"}
        ).status_code
        == 201
    )
    dup = client.post("/admin/staff", json={"username": "alice", "password": "hijack-pw-999"})
    assert dup.status_code == 409
    # The original password still works — the duplicate attempt didn't take over the account.
    fresh = TestClient(client.app)
    assert (
        fresh.post(
            "/admin/login", json={"username": "alice", "password": "alice-pw-123"}
        ).status_code
        == 200
    )
    assert (
        fresh.post(
            "/admin/login", json={"username": "alice", "password": "hijack-pw-999"}
        ).status_code
        == 401
    )


def test_staff_list_shows_accounts_without_password_hashes() -> None:
    client = _as_admin(_client())
    client.post("/admin/staff", json={"username": "alice", "password": "alice-pw-123"})
    body = client.get("/admin/staff")
    assert body.status_code == 200
    usernames = {row["username"] for row in body.json()}
    assert {"admin", "alice"} <= usernames
    assert "password_hash" not in body.text and "$argon2" not in body.text


def test_staff_endpoints_reject_bad_input_and_require_an_admin_session() -> None:
    client = _as_admin(_client())
    assert (
        client.post(
            "/admin/staff", json={"username": "ab", "password": "good-pw-12345"}
        ).status_code
        == 422
    )
    assert (
        client.post("/admin/staff", json={"username": "bob", "password": "short"}).status_code
        == 422
    )

    anon = _client()
    assert anon.get("/admin/staff").status_code == 401
    assert (
        anon.post("/admin/staff", json={"username": "eve", "password": "eve-pw-12345"}).status_code
        == 401
    )

    # A merchant session is not a staff session.
    merchant = _client()
    token = merchant.post(
        "/auth/login", json={"username": "alpha", "password": "alpha-demo"}
    ).json()["token"]
    merchant.headers["Authorization"] = f"Bearer {token}"
    assert merchant.get("/admin/staff").status_code == 401
    assert (
        merchant.post(
            "/admin/staff", json={"username": "eve", "password": "eve-pw-12345"}
        ).status_code
        == 401
    )
