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

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import sessionmaker

from ..adapters.memory import (
    InMemoryLedger,
    InMemoryMerchantStore,
    InMemoryTransactionStore,
)
from ..adapters.sql import SqlLedger, SqlMerchantStore, SqlTransactionStore, make_engine
from ..domains.ledger.ledger import Posting
from ..domains.merchants.models import Merchant
from ..domains.transactions.models import Transaction
from ..domains.transactions.ports import PaymentRail
from ..integrations.pawapay.client import PawaPayClient, ProviderPrediction
from ..integrations.pawapay.rail import PawaPayRail
from ..integrations.pawapay.simulator import SimulatedPaymentRail
from ..integrations.pawapay.status import StatusPoller


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


class ProviderPredictor(Protocol):
    """Resolves a phone number to its mobile-money operator (pawaPay predict-provider).
    Present only when a live pawaPay rail is configured."""

    def predict_provider(self, phone_number: str) -> ProviderPrediction: ...


# Demo merchants for the zero-setup (in-memory) demo and tests — a gas station and a
# pop-up store, mirroring the initial launch set. Their settlement numbers are pawaPay
# **sandbox payout-success** test numbers (…789), so the settle leg completes end-to-end
# against the live sandbox; the simulator ignores them. Real merchants come via onboarding.
_DEMO_MERCHANTS = (
    Merchant(
        id="m_alpha",
        name="Alpha Gas Station",
        short_code="1001",
        settlement_msisdn="243973456789",  # Airtel COD — sandbox payout-success number
        settlement_provider="AIRTEL_COD",
    ),
    Merchant(
        id="m_beta",
        name="Beta Pop-up Store",
        short_code="1002",
        settlement_msisdn="243893456789",  # Orange COD — sandbox payout-success number
        settlement_provider="ORANGE_COD",
    ),
)


def _seeded_merchant_store() -> InMemoryMerchantStore:
    store = InMemoryMerchantStore()
    for merchant in _DEMO_MERCHANTS:
        store.save(merchant)
    return store


@dataclass
class Container:
    store: TxStore
    ledger: LedgerStore
    rail: PaymentRail
    predictor: ProviderPredictor | None = None
    simulated: bool = True  # True when the rail is the in-process simulator
    environment: str = "local"  # local | sandbox | production — gates the demo/ops controls
    merchants: MerchantStore = field(default_factory=_seeded_merchant_store)
    ussd_shortcode: str = "*123#"  # the code customers dial; each merchant's till appended
    pawapay_public_key: str = ""  # PEM; verifies signed callbacks (blank → reject all)
    poller: StatusPoller | None = None  # pawaPay status polling for reconciliation (live rail only)

    @property
    def demo_controls_enabled(self) -> bool:
        """Whether demo/ops controls (e.g. ``POST /demo/reconcile``) may run. Allowed only OFF
        the real-money path — the in-process simulator, or the sandbox — and **never in
        production**, where reconciliation runs via an authenticated trigger / scheduler."""
        return self.simulated or self.environment == "sandbox"


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
        rail: PaymentRail = PawaPayRail(client)
        predictor: ProviderPredictor | None = client
        poller: StatusPoller | None = client  # same client polls status for reconciliation
        simulated = False
    else:
        simulator = SimulatedPaymentRail()
        rail = simulator
        predictor = None
        poller = simulator  # the simulator doubles as a StatusPoller — reconciliation can heal demo txns
        simulated = True

    # Persistence: Postgres when a URL is given (schema managed by Alembic), else memory.
    if database_url:
        engine = make_engine(database_url)
        session_factory = sessionmaker(engine)
        store: TxStore = SqlTransactionStore(session_factory)
        ledger: LedgerStore = SqlLedger(session_factory)
        merchants: MerchantStore = SqlMerchantStore(session_factory)
    else:
        store = InMemoryTransactionStore()
        ledger = InMemoryLedger()
        merchants = _seeded_merchant_store()

    return Container(
        store=store,
        ledger=ledger,
        rail=rail,
        predictor=predictor,
        simulated=simulated,
        merchants=merchants,
        ussd_shortcode=ussd_shortcode,
        pawapay_public_key=pawapay_public_key,
        poller=poller,
        environment=environment,
    )
