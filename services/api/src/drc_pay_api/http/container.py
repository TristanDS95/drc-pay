"""Composition root — holds the shared, persistent adapters.

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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Protocol

from fastapi import Depends, Request
from sqlalchemy.orm import sessionmaker

from ..adapters.memory import (
    InMemoryChargeStore,
    InMemoryLedger,
    InMemoryMerchantStore,
    InMemoryTransactionStore,
)
from ..adapters.sql import (
    SqlChargeStore,
    SqlLedger,
    SqlMerchantStore,
    SqlTransactionStore,
    make_engine,
)
from ..domains.charges.models import Charge
from ..domains.ledger.ledger import Posting
from ..domains.merchants.models import Merchant
from ..domains.transactions.models import Transaction
from ..application.payments import Predictor
from ..domains.transactions.ports import DirectCollectRail, PaymentRail
from ..integrations.pawapay.client import PawaPayClient
from ..integrations.pawapay.rail import PawaPayRail
from ..integrations.pawapay.simulator import SimulatedPaymentRail
from ..integrations.pawapay.status import StatusPoller
from ..integrations.simulated_direct import SimulatedDirectRail
from ..seed import seed_demo_merchants

# On-net-capable operators in the offline demo: M-Pesa & Airtel support a third-party-initiated
# in-app push (so a same-network payment can take the one-leg direct rail). Orange does NOT (its
# flow is a web redirect, not a push), so it always routes through pawaPay. See the research finding
# ``cross-cutting/on-net-direct-operator-apis.md``.
ON_NET_SIM_PROVIDERS = frozenset({"AIRTEL_COD", "VODACOM_MPESA_COD"})


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


@dataclass
class Container:
    store: TxStore
    ledger: LedgerStore
    rail: PaymentRail
    predictor: Predictor | None = None
    simulated: bool = True  # True when the rail is the in-process simulator
    # On-net (same-network) direct rails: operator code → its one-leg C2B rail. A payment whose
    # payer and merchant share an operator in ``on_net_providers`` takes that rail instead of the
    # two-leg pawaPay flow; anything else falls back to pawaPay. Empty by default, so a Container
    # built directly (e.g. in a test) opts out of on-net unless it wires these explicitly.
    direct_rails: Mapping[str, DirectCollectRail] = field(default_factory=dict)
    on_net_providers: frozenset[str] = frozenset()
    environment: str = "local"  # local | sandbox | production — gates the demo/ops controls
    merchants: MerchantStore = field(default_factory=_seeded_merchant_store)
    charges: ChargeStore = field(default_factory=InMemoryChargeStore)
    ussd_shortcode: str = "*123#"  # the code customers dial; each merchant's till appended
    pawapay_public_key: str = ""  # PEM; verifies signed callbacks (blank → reject all)
    poller: StatusPoller | None = None  # pawaPay status polling for reconciliation (live rail only)
    pawapay_client: PawaPayClient | None = None  # the live client, for the startup key fetch below

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
            print("[container] WARNING: could not fetch pawaPay public key — signed callbacks will 401")


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
        # On-net stays on pawaPay until a real operator rail is implemented (the M-Pesa/Airtel
        # adapters still raise NotImplementedError). So with a live rail we hold no direct rails and
        # route everything through pawaPay — the graceful per-operator fallback. Wire an operator
        # here once its adapter + credentials are ready (next: Airtel against its self-serve sandbox).
        direct_rails: Mapping[str, DirectCollectRail] = {}
        on_net_providers: frozenset[str] = frozenset()
    else:
        simulator = SimulatedPaymentRail()
        pawapay_client = None
        rail = simulator
        predictor = None
        poller = simulator  # the simulator doubles as a StatusPoller — reconciliation can heal demo txns
        simulated = True
        # Offline demo: one simulated direct rail stands in for every on-net-capable operator, so a
        # same-network payment exercises the one-leg flow end to end with zero network.
        sim_direct = SimulatedDirectRail()
        direct_rails = {provider: sim_direct for provider in ON_NET_SIM_PROVIDERS}
        on_net_providers = ON_NET_SIM_PROVIDERS

    # Persistence: Postgres when a URL is given (schema managed by Alembic), else memory.
    if database_url:
        engine = make_engine(database_url)
        session_factory = sessionmaker(engine)
        store: TxStore = SqlTransactionStore(session_factory)
        ledger: LedgerStore = SqlLedger(session_factory)
        merchants: MerchantStore = SqlMerchantStore(session_factory)
        charges: ChargeStore = SqlChargeStore(session_factory)
    else:
        store = InMemoryTransactionStore()
        ledger = InMemoryLedger()
        merchants = _seeded_merchant_store()
        charges = InMemoryChargeStore()

    return Container(
        store=store,
        ledger=ledger,
        rail=rail,
        predictor=predictor,
        simulated=simulated,
        direct_rails=direct_rails,
        on_net_providers=on_net_providers,
        merchants=merchants,
        charges=charges,
        ussd_shortcode=ussd_shortcode,
        pawapay_public_key=pawapay_public_key,
        poller=poller,
        pawapay_client=pawapay_client,
        environment=environment,
    )


def get_container(request: Request) -> Container:
    """The shared :class:`Container`, built once at startup and kept on ``app.state``."""
    container: Container = request.app.state.container
    return container


# FastAPI dependency: a route writes ``container: ContainerDep`` and FastAPI injects the shared
# container — replacing the per-file ``_container(request)`` helper that used to be copy-pasted.
ContainerDep = Annotated[Container, Depends(get_container)]
