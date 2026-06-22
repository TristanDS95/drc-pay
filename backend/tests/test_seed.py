"""The demo-merchant seed populates an empty (Postgres-style) store and is idempotent.

This guards the Railway/Postgres deploy: the in-memory demo seeds itself, but a managed
database starts empty, so the entrypoint runs ``seed_demo_merchants`` after migrations.
Verified here against in-memory SQLite (the same SqlMerchantStore that runs on Postgres).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from drc_pay_api.adapters.sql import Base, SqlMerchantStore
from drc_pay_api.seed import DEMO_MERCHANTS, seed_demo_merchants


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def test_seed_populates_empty_store() -> None:
    store = SqlMerchantStore(_factory())
    assert store.all() == []  # a freshly-migrated Postgres table starts empty

    seeded = seed_demo_merchants(store)

    assert set(seeded) == {"m_alpha", "m_beta", "m_gamma"}
    assert {m.id for m in store.all()} == {"m_alpha", "m_beta", "m_gamma"}
    # The QR/pay path looks merchants up by id and till — both must resolve.
    alpha = store.get("m_alpha")
    assert alpha.name == "Alpha Gas Station"
    assert alpha.is_active
    assert store.get_by_short_code("1001") is not None


def test_seed_is_idempotent() -> None:
    store = SqlMerchantStore(_factory())
    seed_demo_merchants(store)
    seed_demo_merchants(store)  # a redeploy re-runs the seed — must not duplicate
    assert len(store.all()) == len(DEMO_MERCHANTS)


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")


if __name__ == "__main__":
    _run_all()
    print("test_seed: all passed")
