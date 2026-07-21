"""Composition root — holds the shared, persistent adapters.

Lives at package level (not under ``http/``) because every channel wires through it —
``main.py`` builds it, the HTTP routes and the USSD handler both consume it. The FastAPI
dependency glue that exposes it to routes lives in ``http/dependencies.py``.

Two independent choices are made here from config:
  - **Rail:** a live ``PawaPayRail`` when both ``DRCPAY_PAWAPAY_*`` credentials are set,
    otherwise the in-process ``SimulatedPaymentRail`` (keeps the demo working with zero
    setup). When live, a provider predictor is also exposed for the route.
  - **Persistence:** the Postgres-backed SQLAlchemy adapters when a database URL is
    given, otherwise the in-memory adapters.

The in-memory path also seeds a couple of demo merchants so the zero-setup demo and the
tests have something to pay. In production merchants are created via the dashboard /
onboarding (flagged); the Postgres path starts empty.

The orchestrator itself is built per-request (in ``routes``) with a fresh trace recorder,
so each call can return its own operations log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .adapters.memory import (
    InMemoryChargeStore,
    InMemoryCredentialStore,
    InMemoryLedger,
    InMemoryMerchantStore,
    InMemorySessionStore,
    InMemoryStaffCredentialStore,
    InMemoryStaffSessionStore,
    InMemoryTransactionStore,
)
from .adapters.sql import (
    SqlChargeStore,
    SqlCredentialStore,
    SqlLedger,
    SqlMerchantStore,
    SqlSessionStore,
    SqlStaffCredentialStore,
    SqlStaffSessionStore,
    SqlTransactionStore,
    make_engine,
)
from .application.payments import Predictor
from .domains.auth.service import AuthService, CredentialStore, SessionStore
from .domains.charges.models import Charge
from .domains.ledger.ledger import Posting
from .domains.merchants.models import Merchant
from .domains.staff.service import StaffAuthService, StaffCredentialStore, StaffSessionStore
from .domains.transactions.models import Transaction
from .domains.transactions.ports import PaymentRail
from .integrations.pawapay.client import PawaPayClient
from .integrations.pawapay.rail import PawaPayRail
from .integrations.pawapay.simulator import SimulatedPaymentRail
from .integrations.pawapay.status import StatusPoller
from .seed import seed_demo_credentials, seed_demo_merchants, seed_demo_staff


class TxStore(Protocol):
    def get(self, transaction_id: str) -> Transaction: ...

    def save(self, transaction: Transaction) -> None: ...

    def all(self) -> list[Transaction]: ...

    def find_by_idempotency_key(self, key: str) -> Transaction | None: ...

    def find_by_op_id(self, op_id: str) -> Transaction | None: ...

    def find_pending(self) -> list[Transaction]: ...


class LedgerStore(Protocol):
    def post(self, posting: Posting) -> None: ...

    def for_transaction(self, transaction_id: str) -> list[Posting]: ...


class MerchantStore(Protocol):
    def get(self, merchant_id: str) -> Merchant: ...

    def get_by_short_code(self, short_code: str) -> Merchant | None: ...

    def save(self, merchant: Merchant) -> None: ...

    def all(self) -> list[Merchant]: ...


class ChargeStore(Protocol):
    def get(self, charge_id: str) -> Charge: ...

    def save(self, charge: Charge) -> None: ...

    def all(self) -> list[Charge]: ...


def _seeded_merchant_store() -> InMemoryMerchantStore:
    # Zero-setup demo + tests: seed the demo merchants (defined once in ``seed.py``). The
    # Postgres path starts empty and is seeded off-production from the entrypoint instead.
    store = InMemoryMerchantStore()
    seed_demo_merchants(store)
    return store


def _seeded_credential_store() -> InMemoryCredentialStore:
    # Same zero-setup principle for logins: the demo merchants' credentials, so local dev
    # and tests can authenticate immediately (the hashes are computed once per process).
    store = InMemoryCredentialStore()
    seed_demo_credentials(store)
    return store


def _seeded_staff_credential_store() -> InMemoryStaffCredentialStore:
    # Zero-setup admin: the demo admin login, so local dev and tests can act as staff.
    store = InMemoryStaffCredentialStore()
    seed_demo_staff(store)
    return store


@dataclass
class Container:
    store: TxStore
    ledger: LedgerStore
    rail: PaymentRail
    predictor: Predictor | None = None
    simulated: bool = True  # True when the rail is the in-process simulator
    environment: str = "local"  # local | sandbox | production — gates the demo/ops controls
    merchants: MerchantStore = field(default_factory=_seeded_merchant_store)
    charges: ChargeStore = field(default_factory=InMemoryChargeStore)
    credentials: CredentialStore = field(default_factory=_seeded_credential_store)
    sessions: SessionStore = field(default_factory=InMemorySessionStore)
    staff_credentials: StaffCredentialStore = field(default_factory=_seeded_staff_credential_store)
    staff_sessions: StaffSessionStore = field(default_factory=InMemoryStaffSessionStore)
    ussd_shortcode: str = "*123#"  # the code customers dial; each merchant's till appended
    pawapay_public_key: str = ""  # PEM; verifies signed callbacks (blank → reject all)
    poller: StatusPoller | None = None  # pawaPay status polling for reconciliation (live rail only)
    pawapay_client: PawaPayClient | None = None  # the live client, for the startup key fetch below
    # Built from the stores above in __post_init__ — one service instance per container, so each
    # login throttle's state survives across requests.
    auth: AuthService = field(init=False)
    staff_auth: StaffAuthService = field(init=False)

    def __post_init__(self) -> None:
        self.auth = AuthService(
            self.credentials, self.sessions, is_merchant_active=self._merchant_active
        )
        self.staff_auth = StaffAuthService(self.staff_credentials, self.staff_sessions)

    def _merchant_active(self, merchant_id: str) -> bool:
        """Login gate: only an ACTIVE merchant may get a session. A pending (self-onboarded,
        awaiting approval), rejected, suspended, or missing merchant is denied."""
        try:
            return self.merchants.get(merchant_id).is_active
        except KeyError:
            return False

    @property
    def demo_controls_enabled(self) -> bool:
        """Whether demo/ops controls (e.g. ``POST /demo/reconcile``) may run. Allowed only OFF
        the real-money path — the in-process simulator, or the sandbox — and **never in
        production**, where reconciliation runs via an authenticated trigger / scheduler."""
        return self.simulated or self.environment == "sandbox"

    def ensure_callback_public_key(self) -> None:
        """If a live pawaPay rail is configured but no callback public key was supplied, fetch
        pawaPay's verification key from their API. Called once at startup (``create_app``), not
        in ``build_container`` — so the offline test suite never makes a network call. Best-effort:
        on failure the key stays blank and signed callbacks 401 until one is available; we never
        crash boot. A statically-set ``DRCPAY_PAWAPAY_PUBLIC_KEY`` takes precedence (skips fetch)."""
        if self.pawapay_public_key or self.pawapay_client is None:
            return
        fetched = self.pawapay_client.get_callback_public_key()
        if fetched:
            self.pawapay_public_key = fetched
            print("[container] fetched pawaPay callback public key for signature verification")
        else:
            print(
                "[container] WARNING: could not fetch pawaPay public key — signed callbacks will 401"
            )


def build_container(
    database_url: str = "",
    pawapay_base_url: str = "",
    pawapay_api_token: str = "",
    ussd_shortcode: str = "*123#",
    pawapay_public_key: str = "",
    environment: str = "local",
) -> Container:
    # Rail: live pawaPay when both credentials are present, else the simulator.
    if pawapay_base_url and pawapay_api_token:
        client = PawaPayClient(base_url=pawapay_base_url, api_token=pawapay_api_token)
        pawapay_client: PawaPayClient | None = client  # for the startup callback-key fetch
        rail: PaymentRail = PawaPayRail(client)
        predictor: Predictor | None = client
        poller: StatusPoller | None = client  # same client polls status for reconciliation
        simulated = False
    else:
        simulator = SimulatedPaymentRail()
        pawapay_client = None
        rail = simulator
        predictor = None
        poller = (
            simulator  # the simulator doubles as a StatusPoller — reconciliation can heal demo txns
        )
        simulated = True

    # Persistence: Postgres when a URL is given (schema managed by Alembic), else memory.
    # A deployed environment MUST have a *working* database — we never silently fall back to the
    # ephemeral in-memory store, which loses every transaction on restart. Local dev/tests
    # (environment == "local") may run in-memory.
    if database_url:
        engine = make_engine(database_url)
        try:  # fail fast if the DB is configured but unreachable — don't run degraded
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise RuntimeError(
                f"DRCPAY_DATABASE_URL is set but the database is unreachable: {exc}"
            ) from exc
        session_factory = sessionmaker(engine)
        store: TxStore = SqlTransactionStore(session_factory)
        ledger: LedgerStore = SqlLedger(session_factory)
        merchants: MerchantStore = SqlMerchantStore(session_factory)
        charges: ChargeStore = SqlChargeStore(session_factory)
        credentials: CredentialStore = SqlCredentialStore(session_factory)
        sessions: SessionStore = SqlSessionStore(session_factory)
        staff_credentials: StaffCredentialStore = SqlStaffCredentialStore(session_factory)
        staff_sessions: StaffSessionStore = SqlStaffSessionStore(session_factory)
        print(f"[container] persistence: Postgres ({environment})")
    elif environment != "local":
        raise RuntimeError(
            f"No DRCPAY_DATABASE_URL set in environment '{environment}'. Refusing to start on the "
            "ephemeral in-memory store (it loses all data on restart). Set DRCPAY_DATABASE_URL to a "
            "Postgres database, or use DRCPAY_ENVIRONMENT=local for in-memory dev."
        )
    else:
        store = InMemoryTransactionStore()
        ledger = InMemoryLedger()
        merchants = _seeded_merchant_store()
        charges = InMemoryChargeStore()
        credentials = _seeded_credential_store()
        sessions = InMemorySessionStore()
        staff_credentials = _seeded_staff_credential_store()
        staff_sessions = InMemoryStaffSessionStore()
        print("[container] persistence: in-memory (local dev — data is NOT durable)")

    return Container(
        store=store,
        ledger=ledger,
        rail=rail,
        predictor=predictor,
        simulated=simulated,
        merchants=merchants,
        charges=charges,
        credentials=credentials,
        sessions=sessions,
        staff_credentials=staff_credentials,
        staff_sessions=staff_sessions,
        ussd_shortcode=ussd_shortcode,
        pawapay_public_key=pawapay_public_key,
        poller=poller,
        pawapay_client=pawapay_client,
        environment=environment,
    )
