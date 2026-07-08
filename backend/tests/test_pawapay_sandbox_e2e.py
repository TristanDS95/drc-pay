"""Live pawaPay **SANDBOX** contract & lifecycle tests — the seam the simulator can't cover.

Every other test in this suite runs against the in-process ``SimulatedPaymentRail``: fast,
deterministic, and offline. But the simulator encodes *our assumptions* about how pawaPay's
real API behaves. If an assumption is wrong (a request shape, the status-endpoint envelope,
the callback key format), every simulator test still passes and production breaks while moving
money. These tests check those assumptions against the real sandbox.

OPT-IN AND OFFLINE-SAFE BY DEFAULT
  - Marked ``sandbox`` and skipped unless ``RUN_PAWAPAY_SANDBOX_E2E=1``. The default ``pytest``
    run (and CI) never makes a network call here.
  - Sandbox credentials are read straight from ``backend/.env`` — the global ``conftest.py``
    deliberately blanks ``DRCPAY_PAWAPAY_*`` in ``os.environ`` to keep the rest of the suite
    offline, so we bypass it and read the file directly.
  - SANDBOX ONLY. No real money moves. Never point these at production credentials.

PAYER NUMBERS ARE pawaPay'S DOCUMENTED SANDBOX TEST NUMBERS
  The operator prefix picks the payer network; the last three digits pick the outcome
  (789 = success, 049 = insufficient funds). These mirror ``http/public_routes.py``
  (_NETWORK_BASE / _OUTCOMES). Source: https://docs.pawapay.io/v2/docs/test_numbers.

RUN IT
    cd backend
    RUN_PAWAPAY_SANDBOX_E2E=1 .venv/bin/pytest tests/test_pawapay_sandbox_e2e.py -v

  Runs end-to-end with just a populated ``.env`` — the documented sandbox numbers are built in.
  Optional overrides:
      PAWAPAY_SANDBOX_NETWORK=vodacom|airtel|orange   # default vodacom
      PAWAPAY_SANDBOX_AMOUNT_MINOR=10000              # default 100.00 (minor units)
      PAWAPAY_SANDBOX_CURRENCY=CDF                     # default CDF
      PAWAPAY_SANDBOX_TIMEOUT=45                       # seconds to wait for a terminal outcome
      PAWAPAY_SANDBOX_COMPLETED_DEPOSIT_ID=...         # enables the refund test
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values

from drc_pay_api.domains.ledger.money import Money
from drc_pay_api.integrations.pawapay.client import PawaPayClient, ProviderPrediction
from drc_pay_api.integrations.pawapay.rail import PawaPayRail, PawaPayRailError
from drc_pay_api.integrations.pawapay.status import Outcome, PawaPayStatus, classify

# Opt-in gate + marker: collected always (so it shows as skipped, documenting intent), but the
# body never runs unless explicitly enabled.
_ENABLED = os.environ.get("RUN_PAWAPAY_SANDBOX_E2E") == "1"
pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        not _ENABLED, reason="set RUN_PAWAPAY_SANDBOX_E2E=1 to run live sandbox tests"
    ),
]

# Read sandbox creds from backend/.env directly (conftest blanks them in os.environ).
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

# pawaPay DRC sandbox test numbers — operator prefix picks the payer network, last three digits
# pick the outcome. Mirrors http/public_routes.py. Source: docs.pawapay.io/v2/docs/test_numbers.
_NETWORK_BASE = {"vodacom": "243813456", "airtel": "243973456", "orange": "243893456"}
_NETWORK_PROVIDER = {"vodacom": "VODACOM_MPESA_COD", "airtel": "AIRTEL_COD", "orange": "ORANGE_COD"}
_SUCCESS_SUFFIX = "789"
_DECLINE_SUFFIX = "049"  # insufficient funds → the collection FAILS

_KNOWN_ACK_STATUSES = {"ACCEPTED", "REJECTED", "DUPLICATE_IGNORED"}
_POLL_INTERVAL_S = 3.0


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default


def _client() -> PawaPayClient:
    base = (_ENV.get("DRCPAY_PAWAPAY_BASE_URL") or "").strip()
    token = (_ENV.get("DRCPAY_PAWAPAY_API_TOKEN") or "").strip()
    if not base or not token:
        pytest.skip("no sandbox base URL / token in backend/.env")
    return PawaPayClient(base_url=base, api_token=token)


def _network() -> str:
    network = _env("PAWAPAY_SANDBOX_NETWORK", "vodacom")
    if network not in _NETWORK_BASE:
        pytest.skip(
            f"PAWAPAY_SANDBOX_NETWORK must be one of {sorted(_NETWORK_BASE)}; got {network!r}"
        )
    return network


def _provider() -> str:
    return _NETWORK_PROVIDER[_network()]


def _payer(suffix: str) -> str:
    """A documented sandbox payer number for the chosen network and a given outcome suffix."""
    return _NETWORK_BASE[_network()] + suffix


def _amount() -> Money:
    # Default 1,000.00 CDF — pawaPay enforces per-provider min/max (VODACOM_MPESA_COD requires
    # 500 < amount < 1,000,000 CDF); the simulator does not, so the default must clear the floor.
    minor = int(_env("PAWAPAY_SANDBOX_AMOUNT_MINOR", "100000"))
    return Money(minor, _env("PAWAPAY_SANDBOX_CURRENCY", "CDF"))


def _poll_deposit_until_terminal(
    client: PawaPayClient, deposit_id: str, timeout_s: float
) -> PawaPayStatus:
    """Poll the real status endpoint until the deposit is terminal or we time out. Mirrors the
    reconciliation sweep's polled path (the production safety net for a missed callback)."""
    deadline = time.monotonic() + timeout_s
    status = client.get_deposit_status(deposit_id)
    while time.monotonic() < deadline and classify(status.status) is Outcome.PENDING:
        time.sleep(_POLL_INTERVAL_S)
        status = client.get_deposit_status(deposit_id)
    return status


def _request_success_deposit(client: PawaPayClient) -> str:
    """Issue an accepted collection for the …789 (success) sandbox number; return its depositId."""
    deposit_id = str(uuid.uuid4())
    ack = client.request_deposit(
        deposit_id=deposit_id,
        phone_number=_payer(_SUCCESS_SUFFIX),
        provider=_provider(),
        amount=_amount(),
    )
    assert ack.accepted, f"sandbox rejected the deposit: {ack.failure_code} / {ack.failure_message}"
    return deposit_id


# --- credential-only contract checks (no money moves) -----------------------


def test_callback_public_key_loads_as_ec_p256() -> None:
    """The single most important live check: the real callback public key must load as an
    EC P-256 key via the exact crypto path our signature verifier uses. If this fails, every
    real pawaPay webhook would 401 in production no matter how correct our verification code is.
    Also doubles as an auth check — a bad token can't reach this endpoint."""
    pem = _client().get_callback_public_key()
    assert pem, "sandbox returned no callback public key (auth failure or endpoint changed?)"
    assert "BEGIN PUBLIC KEY" in pem, f"unexpected key format: {pem[:40]!r}"

    key = serialization.load_pem_public_key(pem.encode())
    assert isinstance(key, ec.EllipticCurvePublicKey), "callback key is not an EC key"
    assert key.curve.name == "secp256r1", f"expected P-256, got {key.curve.name}"


def test_status_of_unknown_deposit_is_fail_safe() -> None:
    """A status lookup for an id pawaPay has never seen must NEVER classify as a terminal
    outcome — our fail-safe (``classify`` → PENDING) has to hold against the real API's
    not-found response, or reconciliation could resolve money on a phantom status."""
    status = _client().get_deposit_status(f"e2e-unknown-{uuid.uuid4()}")
    assert isinstance(status, PawaPayStatus)
    assert classify(status.status) is Outcome.PENDING, (
        f"unknown id classified terminal: {status.status!r}"
    )


# --- money-moving lifecycle checks (documented sandbox numbers) -------------


def test_predict_provider_returns_sane_shape() -> None:
    """predict-provider maps a number to its operator. We validate the request/response
    contract against the live API, not a specific operator (the mapping can change)."""
    prediction = _client().predict_provider(_payer(_SUCCESS_SUFFIX))
    assert isinstance(prediction, ProviderPrediction)
    assert prediction.provider or prediction.country or prediction.phone_number
    if prediction.phone_number:
        assert prediction.phone_number.lstrip("+").isdigit(), (
            "pawaPay should return a sanitised number"
        )


def test_deposit_is_accepted_and_status_is_readable() -> None:
    """The big one: our exact deposit body + provider-aware amount formatting are accepted by
    the REAL pawaPay API, and the real status-endpoint envelope (``{"status":"FOUND","data":…}``)
    parses back out — proving ``client._status`` matches reality, not just our mock."""
    client = _client()
    deposit_id = str(uuid.uuid4())
    ack = client.request_deposit(
        deposit_id=deposit_id,
        phone_number=_payer(_SUCCESS_SUFFIX),
        provider=_provider(),
        amount=_amount(),
    )
    assert ack.status in _KNOWN_ACK_STATUSES, f"unrecognised ack status: {ack.status!r}"
    assert ack.accepted, f"sandbox rejected the deposit: {ack.failure_code} / {ack.failure_message}"
    assert ack.provider_id == deposit_id, "pawaPay should echo our depositId"

    time.sleep(_POLL_INTERVAL_S)
    status = client.get_deposit_status(deposit_id)
    assert status.status is not None, (
        "status endpoint returned nothing readable for an accepted deposit"
    )


def test_successful_deposit_completes() -> None:
    """Happy path on real rails: the …789 sandbox number should settle to COMPLETED via the
    polled lifecycle. Tolerant of sandbox latency — still-pending after the timeout → skip."""
    client = _client()
    timeout_s = float(_env("PAWAPAY_SANDBOX_TIMEOUT", "45"))
    deposit_id = _request_success_deposit(client)

    status = _poll_deposit_until_terminal(client, deposit_id, timeout_s)
    outcome = classify(status.status)
    if outcome is Outcome.PENDING:
        pytest.skip(f"deposit {deposit_id} still pending after {timeout_s:.0f}s (sandbox latency)")
    assert outcome is Outcome.SUCCESS, f"expected success, got {status.status!r}"


def test_declined_deposit_fails() -> None:
    """Failure branch on real rails: the …049 (insufficient funds) sandbox number should resolve
    to FAILED — the branch that, in a real payment, triggers our refund/abort path. Tolerant of
    sandbox latency."""
    client = _client()
    timeout_s = float(_env("PAWAPAY_SANDBOX_TIMEOUT", "45"))
    deposit_id = str(uuid.uuid4())
    ack = client.request_deposit(
        deposit_id=deposit_id,
        phone_number=_payer(_DECLINE_SUFFIX),
        provider=_provider(),
        amount=_amount(),
    )
    # A declined-funds case is accepted synchronously, then FAILS asynchronously (it is not a
    # synchronous rejection). Guard that assumption explicitly.
    assert ack.accepted, f"expected async failure, got a synchronous rejection: {ack.failure_code}"

    status = _poll_deposit_until_terminal(client, deposit_id, timeout_s)
    outcome = classify(status.status)
    if outcome is Outcome.PENDING:
        pytest.skip(f"deposit {deposit_id} still pending after {timeout_s:.0f}s (sandbox latency)")
    assert outcome is Outcome.FAILURE, (
        f"expected failure (insufficient funds), got {status.status!r}"
    )


def test_rail_request_collection_returns_id_on_real_rail() -> None:
    """The production ``PawaPayRail`` port (not just the raw client): an accepted collection
    must return the pawaPay op-id the orchestrator persists for callback correlation/refunds.
    A synchronous rejection surfaces as ``PawaPayRailError`` with the real failure detail."""
    rail = PawaPayRail(_client())
    try:
        deposit_id = rail.request_collection(
            transaction_id="e2e-rail",
            msisdn=_payer(_SUCCESS_SUFFIX),
            amount=_amount(),
            provider=_provider(),
        )
    except PawaPayRailError as exc:  # a real synchronous rejection — fail loudly with why
        pytest.fail(f"sandbox rejected the collection: {exc}")
    assert deposit_id and uuid.UUID(deposit_id), "rail should return the generated depositId"


# --- refund (needs a deposit that has already COMPLETED) --------------------


def test_refund_is_accepted_for_completed_deposit() -> None:
    """Refund reverses a completed deposit. A live refund needs an already-COMPLETED depositId,
    which we don't manufacture inline (it depends on sandbox settlement timing) — supply one via
    PAWAPAY_SANDBOX_COMPLETED_DEPOSIT_ID to exercise this path."""
    deposit_id = _env("PAWAPAY_SANDBOX_COMPLETED_DEPOSIT_ID")
    if not deposit_id:
        pytest.skip(
            "set PAWAPAY_SANDBOX_COMPLETED_DEPOSIT_ID (an already-COMPLETED deposit) for the refund test"
        )
    client = _client()
    ack = client.request_refund(
        refund_id=str(uuid.uuid4()), deposit_id=deposit_id, amount=_amount(), provider=_provider()
    )
    assert ack.status in _KNOWN_ACK_STATUSES, f"unrecognised ack status: {ack.status!r}"
    assert ack.accepted, f"sandbox rejected the refund: {ack.failure_code} / {ack.failure_message}"
