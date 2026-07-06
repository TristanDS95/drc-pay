"""Demo merchants — the businesses the QR codes and the customer app expect (``m_alpha`` /
``m_beta``), and the helper that seeds them.

These are the *single source of truth* for the demo merchants, shared by the in-memory
composition root (``container.py``) and the Postgres seed step below. Their settlement
numbers are pawaPay **sandbox payout-success** test numbers (…789), so the settle leg
completes end-to-end against the live sandbox; the simulator ignores them.

The in-memory demo seeds these at startup. A managed-Postgres deploy, however, starts with an
**empty** ``merchants`` table — in production, merchants arrive via onboarding (a flagged,
separate concern). So for a sandbox/local demo we seed them here, run from the container
entrypoint after migrations (``python -m drc_pay_api.seed``). A **production** deploy is left
empty on purpose.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from .domains.auth.models import MerchantCredential
from .domains.auth.service import hash_password
from .domains.merchants.models import Merchant

DEMO_MERCHANTS: tuple[Merchant, ...] = (
    Merchant(
        id="m_alpha",
        name="Alpha Gas Station",
        short_code="1001",
        settlement_msisdn="243973456789",  # Airtel COD — sandbox payout-success number
        settlement_provider="AIRTEL_COD",
        operator_till="507412",  # demo Airtel "merchant pay" till — on-net hand-off prefers this
    ),
    Merchant(
        id="m_beta",
        name="Beta Pop-up Store",
        short_code="1002",
        settlement_msisdn="243893456789",  # Orange COD — sandbox payout-success number
        settlement_provider="ORANGE_COD",
        # No till on purpose: demonstrates the on-net fallback to send-to-number (P2P).
    ),
    Merchant(
        id="m_gamma",
        name="Gamma Market",
        short_code="1003",
        settlement_msisdn="243813456789",  # Vodacom M-Pesa COD — sandbox payout-success number
        settlement_provider="VODACOM_MPESA_COD",
        operator_till="660145",  # demo M-Pesa "buy goods" till — on-net hand-off prefers this
    ),
)


# Demo logins (sandbox/local only — production seeds nothing): username = the merchant's
# name, password = "<username>-demo". Deliberately guessable BECAUSE they only ever exist
# behind the sandbox's shared demo gate; real merchants get real credentials via onboarding.
DEMO_LOGINS: tuple[tuple[str, str, str], ...] = (  # (merchant_id, username, password)
    ("m_alpha", "alpha", "alpha-demo"),
    ("m_beta", "beta", "beta-demo"),
    ("m_gamma", "gamma", "gamma-demo"),
)


@lru_cache(maxsize=1)
def _demo_credentials() -> tuple[MerchantCredential, ...]:
    """The demo credentials with their Argon2id hashes. Cached: hashing is deliberately slow
    (~0.1s each), and tests build many containers per process — hash the three once."""
    return tuple(
        MerchantCredential(merchant_id=mid, username=user, password_hash=hash_password(pw))
        for mid, user, pw in DEMO_LOGINS
    )


class _MerchantStore(Protocol):
    """The minimal store surface the seed needs (``InMemoryMerchantStore`` and
    ``SqlMerchantStore`` both satisfy it)."""

    def save(self, merchant: Merchant) -> None: ...


class _CredentialStore(Protocol):
    def save(self, credential: MerchantCredential) -> None: ...


def seed_demo_merchants(merchants: _MerchantStore) -> list[str]:
    """Idempotently ensure each demo merchant exists, returning the ids seeded. ``save`` upserts
    by primary key, so this never duplicates and never touches other (e.g. onboarded) merchants —
    safe to run on every deploy."""
    for merchant in DEMO_MERCHANTS:
        merchants.save(merchant)
    return [merchant.id for merchant in DEMO_MERCHANTS]


def seed_demo_credentials(credentials: _CredentialStore) -> list[str]:
    """Idempotently ensure each demo merchant can log in. Same upsert semantics as the
    merchants above; never touches onboarded merchants' credentials."""
    for credential in _demo_credentials():
        credentials.save(credential)
    return [credential.username for credential in _demo_credentials()]


def main() -> None:
    """Entrypoint seed: upsert the demo merchants into the configured Postgres database. A no-op
    when no database is configured (the in-memory demo seeds itself) or in production (which starts
    empty by design). Gating lives here, so the shell entrypoint can call it unconditionally."""
    from sqlalchemy.orm import sessionmaker

    from .adapters.sql import SqlCredentialStore, SqlMerchantStore, make_engine
    from .config import settings

    if not settings.database_url:
        print("[seed] no DRCPAY_DATABASE_URL — nothing to seed (the in-memory demo seeds itself).")
        return
    if settings.environment not in {"local", "sandbox"}:
        print(
            f"[seed] environment={settings.environment!r} — skipping demo seed "
            "(production starts empty; merchants come via onboarding)."
        )
        return
    session_factory = sessionmaker(make_engine(settings.database_url))
    seeded = seed_demo_merchants(SqlMerchantStore(session_factory))
    logins = seed_demo_credentials(SqlCredentialStore(session_factory))
    print(f"[seed] demo merchants ready: {', '.join(seeded)}")
    print(f"[seed] demo console logins ready: {', '.join(logins)} (password: <username>-demo)")


if __name__ == "__main__":
    main()
