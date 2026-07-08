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

from dataclasses import replace

from fastapi.testclient import TestClient

from drc_pay_api import config
from drc_pay_api.application.payments import start_merchant_payment
from drc_pay_api.container import build_container
from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.domains.transactions.models import Transaction
from drc_pay_api.domains.transactions.ports import IdempotentTransactionStore
from drc_pay_api.main import create_app

from conftest import as_merchant
from drc_pay_api.http.ussd_routes import _SWEEP_EVERY, SlidingWindowLimiter
from drc_pay_api.ussd.session import UssdHandler, UssdRequest, UssdResponse


class _BlindOnceStore:
    """Wraps a transaction store so the FIRST idempotency lookup returns None — simulating a
    pre-check that races ahead of the race-winner's commit — while every other call delegates.
    Used to drive the concurrent-duplicate branch of ``start_merchant_payment``."""

    def __init__(self, inner: IdempotentTransactionStore) -> None:
        self._inner = inner
        self._blinded = False

    def find_by_idempotency_key(self, key: str) -> Transaction | None:
        if not self._blinded:
            self._blinded = True
            return None
        return self._inner.find_by_idempotency_key(key)

    def get(self, transaction_id: str) -> Transaction:
        return self._inner.get(transaction_id)

    def save(self, transaction: Transaction) -> None:
        self._inner.save(transaction)


def run_session(
    handler: UssdHandler, session_id: str, msisdn: str, inputs: list[str]
) -> list[UssdResponse]:
    """Simulate an aggregator driving a whole conversation: the initial dial, then each
    input - sending the **accumulated** text each step, as real aggregators do. Returns
    every response (the last is the terminal END)."""
    responses = [handler.handle(UssdRequest(session_id, msisdn, ""))]
    accumulated: list[str] = []
    for value in inputs:
        accumulated.append(value)
        responses.append(handler.handle(UssdRequest(session_id, msisdn, "*".join(accumulated))))
    return responses


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


def test_ussd_ambiguous_or_exotic_amounts_are_rejected() -> None:
    # Thousands-grouped and non-plain-decimal inputs must re-prompt, never be silently
    # reinterpreted: "1,000" (meant as a thousand) must NOT become 1.00, and scientific
    # notation / digit separators / Unicode digits must not slip through Decimal.
    handler = UssdHandler(build_container())
    for bad in ["1,000", "10.000", "1e3", "1_000", "１０"]:
        r = handler.handle(UssdRequest(f"amt-{bad}", "243a", f"1001*{bad}"))
        assert r.continue_session and "invalide" in r.message.lower(), bad


def test_ussd_inactive_till_ends_without_retargeting_to_another_merchant() -> None:
    # A dial-through for a since-deactivated till must END on it, not skip ahead and let the
    # next token (here 1002, Beta's active till) resolve as a different merchant — which would
    # silently pay the wrong business.
    container = build_container()
    handler = UssdHandler(container)
    container.merchants.save(replace(container.merchants.get("m_alpha"), status="suspended"))
    r = handler.handle(UssdRequest("inact-1", "243a", "1001*1002"))
    assert not r.continue_session
    assert "n'accepte pas" in r.message.lower()  # inactive-till END, not a confirm prompt
    assert "Beta" not in r.message  # never retargeted to merchant 1002
    assert container.store.all() == []  # nothing initiated


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
    # On-net with no operator till → the closing message sends the customer to the number.
    container = build_container()
    handler = UssdHandler(container)
    # Remove gamma's operator till for THIS container only. dataclasses.replace makes a copy;
    # mutating the object returned by get() in place would corrupt the shared seed fixture and
    # break whichever on-net till test happens to run afterward.
    merchant = replace(container.merchants.get("m_gamma"), operator_till=None)
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


def test_ussd_idempotency_key_is_scoped_to_the_customer_msisdn() -> None:
    # Aggregators recycle session ids. If the key were (session, till, amount) only, a *second*
    # customer's identical confirm under a reused session id would resolve to the FIRST customer's
    # transaction — telling them "paid" while nothing was initiated for their number. The msisdn is
    # part of the key, so two customers get two distinct payments.
    container = build_container()
    handler = UssdHandler(container)
    handler.handle(UssdRequest("recycled", "243800000001", "1001*10*1"))
    handler.handle(UssdRequest("recycled", "243800000002", "1001*10*1"))
    txs = container.store.all()
    assert len(txs) == 2
    assert {t.customer_msisdn for t in txs} == {"243800000001", "243800000002"}


def test_start_merchant_payment_survives_a_concurrent_idempotency_race() -> None:
    # Losing an idempotency race: our pre-check finds nothing (the winner has not committed yet),
    # then the store's unique guard rejects our save. We must return the winner's transaction, not
    # 500 and not open a second collection. _BlindOnce reproduces the pre-check-then-collide window.
    container = build_container()
    merchant = container.merchants.get("m_alpha")  # cross-network → routed (has a rail leg)

    def _start(store: IdempotentTransactionStore) -> str:
        return start_merchant_payment(
            store=store,
            ledger=container.ledger,
            rail=container.rail,
            predictor=container.predictor,
            simulated=container.simulated,
            customer_msisdn="243800000001",
            merchant=merchant,
            amount=Money.from_major("10", "USD"),
            idempotency_key="race",
        )

    winner = _start(container.store)
    loser = _start(_BlindOnceStore(container.store))
    assert loser == winner  # returned the winner, never raised
    assert len(container.store.all()) == 1  # exactly one payment, the race-loser opened nothing


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
    assert client.post("/ussd", json=body, headers={"X-USSD-Secret": "wrong"}).status_code == 401
    ok = client.post("/ussd", json=body, headers={"X-USSD-Secret": "agg-secret"})
    assert ok.status_code == 200 and ok.text.startswith("CON")


def test_ussd_non_ascii_secret_header_is_rejected_not_crashed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A non-ASCII X-USSD-Secret (headers arrive latin-1-decoded) must be a clean 401, not a
    # TypeError → 500 from secrets.compare_digest on a non-ASCII str.
    monkeypatch.setattr(config.settings, "ussd_shared_secret", "agg-secret")
    client = TestClient(create_app())
    # Raw bytes on the wire (0xE9): the client would reject a non-ASCII str, but a real aggregator
    # or attacker can send arbitrary bytes, which Starlette hands us latin-1-decoded as "café".
    r = client.post(
        "/ussd",
        json={"session_id": "sec-2", "msisdn": "243800000001", "text": ""},
        headers={"X-USSD-Secret": b"caf\xe9"},
    )
    assert r.status_code == 401


def test_ussd_rate_limit_per_msisdn() -> None:
    client = TestClient(create_app())
    body = {"session_id": "rl-1", "msisdn": "243800000002", "text": ""}
    responses = [client.post("/ussd", json=body) for _ in range(16)]
    # USSD always answers 200 with a wire body: 15 admitted (ask-till CON), the 16th throttled with
    # a wire END the customer can read — not a JSON 429 the aggregator would render as a raw error.
    assert all(r.status_code == 200 for r in responses)
    assert all(r.text.startswith("CON") for r in responses[:15])
    assert responses[15].text.startswith("END") and "minute" in responses[15].text.lower()
    # A different number is unaffected — the limit is per msisdn.
    other = client.post("/ussd", json={**body, "msisdn": "243800000003"})
    assert other.status_code == 200 and other.text.startswith("CON")


def test_ussd_msisdn_plus_prefix_is_one_rate_limit_identity() -> None:
    # '+243…' and '243…' are the same subscriber; an abuser must not double the per-number budget
    # by toggling the '+'. 15 requests as the plain form, then the 16th as the '+' form is throttled.
    client = TestClient(create_app())
    for _ in range(15):
        assert (
            client.post(
                "/ussd", json={"session_id": "n", "msisdn": "243800000002", "text": ""}
            ).status_code
            == 200
        )
    throttled = client.post(
        "/ussd", json={"session_id": "n", "msisdn": "+243800000002", "text": ""}
    )
    assert throttled.text.startswith("END") and "minute" in throttled.text.lower()


def test_ussd_normalizes_the_plus_prefix_in_storage() -> None:
    # The stored msisdn (and thus the idempotency key) is canonical digits-only, so '+243…' and
    # '243…' retries of one session key identically instead of forking into two transactions.
    client = as_merchant(TestClient(create_app()))
    for text in ["", "1001", "1001*10", "1001*10*1"]:
        client.post("/ussd", json={"session_id": "z", "msisdn": "+243800000009", "text": text})
    listed = client.get("/transactions").json()
    assert listed[0]["customer_msisdn"] == "243800000009"  # '+' stripped


def test_ussd_rejects_newline_and_unicode_digit_msisdns() -> None:
    # The msisdn is stored and rendered in the console; a trailing newline (old '$' allowed it) or
    # Unicode/fullwidth digits (old '\\d' matched them) must be refused at the edge.
    client = TestClient(create_app())
    for bad in ["243800000001\n", "٢٤٣٨٠٠٠٠", "１２３４５６"]:
        r = client.post("/ussd", json={"session_id": "x", "msisdn": bad, "text": ""})
        assert r.status_code == 422, bad


def test_ussd_rejects_an_oversized_text_body() -> None:
    # An unbounded text field split on '*' is a cheap memory/CPU DoS; the field is length-capped.
    client = TestClient(create_app())
    r = client.post("/ussd", json={"session_id": "x", "msisdn": "243800000001", "text": "1" * 5000})
    assert r.status_code == 422


def test_ussd_rate_limiter_does_not_grow_unbounded() -> None:
    # An attacker spraying unique msisdns must not leak one map entry per number forever. With a
    # zero-length window every key ages out immediately, so the amortized sweep reclaims them.
    limiter = SlidingWindowLimiter(limit=100, window_seconds=0.0)
    for i in range(_SWEEP_EVERY + 50):
        limiter.allow(f"243{i:012d}")
    assert len(limiter._hits) < _SWEEP_EVERY  # bounded, not one-entry-per-distinct-key


def test_production_refuses_to_boot_without_the_ussd_secret(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    monkeypatch.setattr(config.settings, "environment", "production")
    monkeypatch.setattr(config.settings, "ussd_shared_secret", "")
    with pytest.raises(RuntimeError, match="USSD_SHARED_SECRET"):
        create_app()


def test_boot_refuses_an_unrecognized_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    # A typo of "production" must NOT fail open: an unknown environment silently skips every
    # exact-match safety gate, so it must refuse to boot instead.
    monkeypatch.setattr(config.settings, "environment", "prod")
    with pytest.raises(RuntimeError, match="Unknown DRCPAY_ENVIRONMENT"):
        create_app()


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if (
            name.startswith("test_")
            and callable(fn)
            and "monkeypatch" not in fn.__code__.co_varnames
        ):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_ussd: all passed (run via pytest for the monkeypatch tests)")
