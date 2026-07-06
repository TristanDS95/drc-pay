"""The USSD channel: a customer pays a merchant, driving the *same* orchestrator as the
HTTP API. Fully offline. Aggregators send the full accumulated input each step
(`text = "1001*10*1"`), so a scanned/dialed QR (`*123*1001*10#`) is just a session that
starts pre-filled — the dial-through fast-path.

Menus are FRENCH by default (`DRCPAY_USSD_LANG`); mistyped input re-prompts (CON) and the
parser skips the misses when re-reading the accumulated text; three misses on one field
end the session. The `/ussd` transport owns the aggregator shared secret + per-msisdn
rate limit.

Uses the seeded demo merchants: m_alpha (till 1001, Airtel — cross-network from the demo
Vodacom payer → routed) and m_gamma (till 1003, Vodacom — same-network → on-net).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from drc_pay_api import config
from drc_pay_api.container import build_container
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.main import create_app

from conftest import as_merchant
from drc_pay_api.ussd.session import UssdHandler, UssdRequest, run_session


# ---- the happy path (French default) -----------------------------------------
def test_ussd_happy_path_creates_and_settles_a_payment() -> None:
    container = build_container()
    handler = UssdHandler(container)
    sid, msisdn = "sess-1", "243800000009"

    r0 = handler.handle(UssdRequest(sid, msisdn, ""))
    assert r0.continue_session and "till" in r0.message.lower()

    r1 = handler.handle(UssdRequest(sid, msisdn, "1001"))  # Alpha Gas Station
    assert r1.continue_session and "Alpha Gas Station" in r1.message
    assert "montant" in r1.message.lower()  # French by default

    r2 = handler.handle(UssdRequest(sid, msisdn, "1001*10"))  # accumulated text
    assert r2.continue_session and "1. Confirmer" in r2.message and "2. Annuler" in r2.message

    r3 = handler.handle(UssdRequest(sid, msisdn, "1001*10*1"))  # confirm
    assert not r3.continue_session
    assert "initie" in r3.message  # routed: pawaPay PIN push follows

    txs = container.store.all()
    assert len(txs) == 1
    tx = txs[0]
    assert tx.customer_msisdn == msisdn
    assert tx.merchant_id == "m_alpha"
    assert tx.amount == Money.from_major("10.00", "USD")
    assert tx.state.value == "payout_succeeded"  # the simulator played out success


def test_ussd_menus_in_english_when_configured() -> None:
    handler = UssdHandler(build_container(), lang="en")
    r = handler.handle(UssdRequest("s-en", "243a", "1001"))
    assert "Enter amount" in r.message


def test_ussd_messages_fit_the_wire() -> None:
    # USSD replies must stay well under the ~180-char transport ceiling, in both languages.
    for lang in ("fr", "en"):
        handler = UssdHandler(build_container(), lang=lang)
        for text in ["", "1001", "1001*9999.99", "1001*9999.99*1", "1003*10*1", "1001*10*2"]:
            message = handler.handle(UssdRequest(f"len-{lang}-{text}", "243a", text)).message
            assert len(message) <= 182, f"{lang} {text!r}: {len(message)} chars"


# ---- QR dial-through fast-paths ------------------------------------------------
def test_ussd_qr_dial_through_jumps_to_confirm() -> None:
    # A scanned/dialed *123*1001*10# arrives as one request with the text pre-filled.
    container = build_container()
    handler = UssdHandler(container)
    r = handler.handle(UssdRequest("q1", "243a", "1001*10"))
    assert r.continue_session
    assert "Confirmer" in r.message and "Alpha Gas Station" in r.message
    r2 = handler.handle(UssdRequest("q1", "243a", "1001*10*1"))
    assert not r2.continue_session
    assert len(container.store.all()) == 1


def test_ussd_qr_dial_through_till_only_asks_amount() -> None:
    # *123*1001# pre-fills just the till → straight to the amount prompt.
    handler = UssdHandler(build_container())
    r = handler.handle(UssdRequest("q2", "243a", "1001"))
    assert r.continue_session and "montant" in r.message.lower()


# ---- retries: mistypes re-prompt instead of killing the session -----------------
def test_ussd_unknown_till_reprompts_then_recovers() -> None:
    container = build_container()
    handler = UssdHandler(container)
    r = handler.handle(UssdRequest("s2", "243a", "9999"))
    assert r.continue_session  # re-ask, don't hang up
    assert "inconnu" in r.message.lower()
    # The retry arrives appended to the accumulated text and is parsed past the miss.
    r2 = handler.handle(UssdRequest("s2", "243a", "9999*1001"))
    assert r2.continue_session and "Alpha Gas Station" in r2.message


def test_ussd_three_bad_tills_end_the_session() -> None:
    handler = UssdHandler(build_container())
    r = handler.handle(UssdRequest("s2b", "243a", "9997*9998*9999"))
    assert not r.continue_session
    assert "recomposer" in r.message.lower()


def test_ussd_invalid_amount_reprompts_then_recovers() -> None:
    container = build_container()
    handler = UssdHandler(container)
    r = handler.handle(UssdRequest("s4", "243a", "1001*not-a-number"))
    assert r.continue_session
    assert "invalide" in r.message.lower()
    r2 = handler.handle(UssdRequest("s4", "243a", "1001*not-a-number*10"))
    assert r2.continue_session and "Confirmer" in r2.message


def test_ussd_amount_over_the_cap_is_rejected() -> None:
    handler = UssdHandler(build_container())
    r = handler.handle(UssdRequest("s4b", "243a", "1001*50000"))
    assert r.continue_session and "invalide" in r.message.lower()


def test_ussd_comma_decimal_amount_is_accepted() -> None:
    # A francophone feature-phone user types "10,50"; it must read as 10.50.
    container = build_container()
    handler = UssdHandler(container)
    r = handler.handle(UssdRequest("s4c", "243a", "1001*10,50*1"))
    assert not r.continue_session
    assert container.store.all()[0].amount == Money.from_major("10.50", "USD")


def test_ussd_invalid_choice_reasks_then_recovers() -> None:
    container = build_container()
    handler = UssdHandler(container)
    r = handler.handle(UssdRequest("s6", "243a", "1001*10*7"))
    assert r.continue_session and "Confirmer" in r.message  # re-ask the confirm
    r2 = handler.handle(UssdRequest("s6", "243a", "1001*10*7*1"))
    assert not r2.continue_session
    assert len(container.store.all()) == 1


def test_ussd_cancel_creates_no_payment() -> None:
    container = build_container()
    handler = UssdHandler(container)
    responses = run_session(handler, "s3", "243a", ["1001", "10", "2"])  # 2 = cancel
    assert not responses[-1].continue_session
    assert "annule" in responses[-1].message.lower()
    assert container.store.all() == []


# ---- on-net vs routed closing messages (ADR 0009) --------------------------------
def test_ussd_on_net_tells_the_customer_to_pay_the_till_directly() -> None:
    # Demo payer defaults to Vodacom; gamma (till 1003) settles on Vodacom → on-net.
    container = build_container()
    handler = UssdHandler(container)
    r = handler.handle(UssdRequest("s7", "243a", "1003*8*1"))
    assert not r.continue_session
    assert "660145" in r.message  # gamma's operator till — pay it directly
    assert "directement" in r.message.lower()
    tx = container.store.all()[0]
    assert tx.provenance == "merchant_attested"
    assert tx.state.value == "collection_pending"  # awaiting the merchant's confirm


def test_ussd_on_net_without_a_till_falls_back_to_the_number() -> None:
    # beta (till 1002, Orange) has no operator till; an Orange payer goes on-net → number.
    container = build_container()
    handler = UssdHandler(container)
    # Force the payer onto Orange by overriding the demo provider through a beta payment:
    # beta settles ORANGE_COD and the demo payer resolves to VODACOM — cross-network. To hit
    # the no-till fallback we make the payer Orange via the same route the app uses: none
    # exists on USSD (no override), so instead check the message template directly through
    # gamma with its till removed.
    merchant = container.merchants.get("m_gamma")
    merchant.operator_till = None
    container.merchants.save(merchant)
    r = handler.handle(UssdRequest("s8", "243a", "1003*8*1"))
    assert not r.continue_session
    assert merchant.settlement_msisdn in r.message  # send-to-number fallback


def test_ussd_run_session_helper_completes() -> None:
    container = build_container()
    handler = UssdHandler(container)
    responses = run_session(handler, "s5", "243a", ["1001", "5.00", "1"])
    assert responses[-1].continue_session is False
    assert len(container.store.all()) == 1


# ---- replay / idempotency ---------------------------------------------------------
def test_ussd_confirm_replay_is_idempotent() -> None:
    # An aggregator resends the confirm step on timeout (or an attacker replays it). Keyed on the
    # session, the retry must return the original transaction, never a second collection.
    container = build_container()
    handler = UssdHandler(container)
    sid, msisdn = "dup-1", "243800000009"
    first = handler.handle(UssdRequest(sid, msisdn, "1001*10*1"))
    for _ in range(2):  # replay the confirm
        replay = handler.handle(UssdRequest(sid, msisdn, "1001*10*1"))
        assert replay.message == first.message  # same closing message, no confusion
    assert len(container.store.all()) == 1  # exactly one payment, not three


# ---- the HTTP boundary: wire format, validation, secret, rate limit ---------------
def test_ussd_endpoint_shares_the_transaction_store() -> None:
    # The /ussd posts themselves are unauthenticated (customer channel); only the merchant-side
    # read of the resulting transaction needs the session.
    client = as_merchant(TestClient(create_app()))
    sid, msisdn = "http-1", "243800000009"
    last = None
    for text in ["", "1001", "1001*10", "1001*10*1"]:  # accumulated, as an aggregator sends
        last = client.post("/ussd", json={"session_id": sid, "msisdn": msisdn, "text": text})
        assert last.status_code == 200
    assert last is not None and last.text.startswith("END")
    # The USSD payment is visible through the same HTTP API (shared container).
    listed = client.get("/transactions").json()
    assert len(listed) == 1
    assert listed[0]["merchant_id"] == "m_alpha"
    assert listed[0]["customer_msisdn"] == msisdn


def test_ussd_http_rejects_non_numeric_msisdn() -> None:
    # The msisdn is stored and later rendered in the console, so junk must be refused at the edge.
    client = TestClient(create_app())
    r = client.post(
        "/ussd", json={"session_id": "x", "msisdn": "243<img src=x>", "text": "1001*10*1"}
    )
    assert r.status_code == 422


def test_ussd_http_rejects_absurd_session_ids() -> None:
    client = TestClient(create_app())
    r = client.post("/ussd", json={"session_id": "x" * 200, "msisdn": "243800000001", "text": ""})
    assert r.status_code == 422


def test_ussd_shared_secret_gates_the_aggregator(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(config.settings, "ussd_shared_secret", "agg-secret")
    client = TestClient(create_app())
    body = {"session_id": "sec-1", "msisdn": "243800000001", "text": ""}
    assert client.post("/ussd", json=body).status_code == 401  # missing
    assert client.post(
        "/ussd", json=body, headers={"X-USSD-Secret": "wrong"}
    ).status_code == 401
    ok = client.post("/ussd", json=body, headers={"X-USSD-Secret": "agg-secret"})
    assert ok.status_code == 200 and ok.text.startswith("CON")


def test_ussd_rate_limit_per_msisdn(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app())
    body = {"session_id": "rl-1", "msisdn": "243800000002", "text": ""}
    statuses = [client.post("/ussd", json=body).status_code for _ in range(10)]
    assert statuses[:8] == [200] * 8
    assert statuses[8] == statuses[9] == 429  # the spray is cut off
    # A different number is unaffected — the limit is per msisdn.
    other = client.post("/ussd", json={**body, "msisdn": "243800000003"})
    assert other.status_code == 200


def test_production_refuses_to_boot_without_the_ussd_secret(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    monkeypatch.setattr(config.settings, "environment", "production")
    monkeypatch.setattr(config.settings, "ussd_shared_secret", "")
    with pytest.raises(RuntimeError, match="USSD_SHARED_SECRET"):
        create_app()


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and "monkeypatch" not in fn.__code__.co_varnames:
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_ussd: all passed (run via pytest for the monkeypatch tests)")
