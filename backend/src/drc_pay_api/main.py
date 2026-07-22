"""FastAPI application factory.

Thin HTTP layer: routing, middleware, and serialization only. All money logic lives
in ``drc_pay_api.domains``, framework-agnostic, so the same core can later be driven
by the USSD gateway without reimplementation.

``create_app()`` builds a fresh application (with its own in-memory wiring), so tests
spin up isolated instances. The module-level ``app`` is what uvicorn serves.
"""

from __future__ import annotations

import asyncio
import base64
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .container import build_container
from .http.admin_merchants_routes import admin_merchants_router
from .http.admin_routes import admin_router
from .http.auth_routes import auth_router
from .http.demo_routes import demo_router
from .http.merchant_api import merchant_api_router
from .http.onboarding_routes import onboarding_router
from .http.public_routes import public_router
from .http.ussd_routes import SlidingWindowLimiter, ussd_router
from .http.webhook_routes import webhook_router
from .jobs.reconciliation.sweep import run_reconciliation
from .ussd.session import UssdHandler

# The shared Basic password now gates only the DEVELOPER shell: the API docs and the /demo/*
# controls. It never gates:
#   - the pawaPay callback under /webhooks/ (verified by RFC-9421 signature instead),
#   - the platform's health probe,
#   - customer-facing paths (a customer who scans a QR has no login),
#   - /signup: merchant self-onboarding is public by design — a business registering itself
#     has no demo password (it creates a PENDING merchant that can't act until approved),
#   - the merchant API + /auth (each merchant authenticates with their OWN session — a shared
#     password would have to be handed to every merchant, defeating per-merchant auth).
#   - /demo/credentials: fetched in the background by the sign-in page, and some browsers don't
#     attach cached Basic credentials to fetch(). It publishes no passwords off local.
#   - **the two console PAGES themselves** (/console, /staff, and the root that redirects to
#     /console). They are login forms and nothing else — every byte of data behind them needs a
#     merchant or staff session. Gating them meant a real business could not even reach the
#     sign-up form without being handed the shared password, which blocked self-registration
#     entirely. The password protecting a login form added no security, only a barrier.
_AUTH_EXEMPT = {"/health", "/demo/credentials", "/"}
_AUTH_EXEMPT_PREFIXES = ("/webhooks/",)
_PUBLIC_PREFIXES = ("/pay", "/ussd", "/public", "/customer", "/signup", "/console", "/staff")
_SESSION_GATED_PREFIXES = ("/auth", "/admin", "/transactions", "/merchants", "/charges")


async def _reconcile_loop(app: FastAPI, interval: int) -> None:
    """Periodically run the reconciliation sweep — the production trigger for the missed-callback
    safety net. The sweep itself is synchronous (blocking pawaPay polls), so it runs in a worker
    thread to keep the event loop free. It never raises out of here: one bad pass is logged and the
    loop continues, so the safety net can't be taken down by a transient error."""
    container = app.state.container
    while True:
        await asyncio.sleep(interval)
        try:
            summary = await asyncio.to_thread(
                run_reconciliation,
                store=container.store,
                rail=container.rail,
                ledger=container.ledger,
                poller=container.poller,
            )
            if summary.resolved:
                print(f"[reconcile] swept {summary.total} pending, healed {summary.resolved}")
        except Exception as exc:  # the safety-net loop must survive any single failure
            print(f"[reconcile] sweep error (retrying next interval): {exc}")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the reconciliation sweep on a schedule while the app is up — but only on a live rail.
    The in-process simulator has nothing to poll, and tests must not spawn background timers, so
    the loop is skipped when ``container.simulated`` is True."""
    container = app.state.container
    task: asyncio.Task[None] | None = None
    if not container.simulated and container.poller is not None:
        interval = settings.reconcile_interval_seconds
        task = asyncio.create_task(_reconcile_loop(app, interval))
        print(f"[reconcile] scheduled sweep every {interval}s")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def _basic_auth_ok(authorization: str, password: str) -> bool:
    if not authorization.startswith("Basic "):
        return False
    try:
        user, _, supplied = base64.b64decode(authorization[6:]).decode().partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return secrets.compare_digest(user, "drcpay") and secrets.compare_digest(supplied, password)


_KNOWN_ENVIRONMENTS = frozenset({"local", "sandbox", "production"})


def create_app() -> FastAPI:
    # Fail CLOSED on an unrecognized environment. Every safety gate below keys off an exact
    # environment string, so a typo ("prod", "Production", "production ") would silently match
    # neither the sandbox nor the production guard and boot a live deploy wide open. Reject it.
    if settings.environment not in _KNOWN_ENVIRONMENTS:
        raise RuntimeError(
            f"Unknown DRCPAY_ENVIRONMENT {settings.environment!r}. Must be one of "
            f"{sorted(_KNOWN_ENVIRONMENTS)}. Refusing to start: an unrecognized environment "
            "silently skips the sandbox and production safety gates."
        )
    # The merchant API is session-gated in EVERY environment (per-merchant login — see
    # http/dependencies.py), so it no longer depends on the shared password. The sandbox still
    # refuses to boot without one: its demo shell (console page, docs, demo endpoints) is
    # meant to be gated, and the gate fails OPEN when no password is set. Production runs
    # without a shared password by design; local dev / tests stay open.
    if settings.environment == "sandbox" and not settings.basic_auth_password:
        raise RuntimeError(
            "No DRCPAY_BASIC_AUTH_PASSWORD set in environment 'sandbox'. Refusing to start: "
            "the hosted demo shell (console, docs, demo endpoints) would be public. Set a "
            "password, or use DRCPAY_ENVIRONMENT=local for ungated local dev."
        )
    # /ussd initiates real payment prompts and is necessarily public to the aggregator; in
    # production it must be locked to that aggregator (security roadmap, Gate A). Fail-fast
    # like the DB and sandbox-password guards. Local/sandbox stay open so the console's dial
    # simulator works.
    if settings.environment == "production" and not settings.ussd_shared_secret:
        raise RuntimeError(
            "No DRCPAY_USSD_SHARED_SECRET set in environment 'production'. Refusing to start: "
            "/ussd would accept payment prompts from anyone. Set the aggregator's shared secret."
        )

    app = FastAPI(title="DRC Pay — Merchant Acquiring API", version="0.0.1", lifespan=_lifespan)

    # DEV ONLY: let the local web Merchant Console (a different origin) call the API.
    # Production locks this down to known origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Cache discipline. StaticFiles sends no Cache-Control, so browsers heuristically cache
    # the console/customer pages and keep RUNNING OLD PAGE CODE across reloads — during the
    # login saga, stale pages spoke a header protocol the server no longer had. ``no-cache``
    # = store but ALWAYS revalidate (ETag/304 keeps it cheap): a plain reload is guaranteed
    # to run the deployed code. The session-gated API gets ``no-store``: auth responses must
    # never be replayed from a cache.
    @app.middleware("http")
    async def _cache_discipline(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith(_SESSION_GATED_PREFIXES) or path == "/demo/credentials":
            response.headers["Cache-Control"] = "no-store"
        elif path == "/" or path.startswith(("/console", "/customer")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # Optional shared-password gate for the hosted sandbox demo SHELL. Off when no password is
    # set (local dev / tests / production). Exempts the webhook + health + customer paths, the
    # session-gated merchant API, and CORS preflights.
    @app.middleware("http")
    async def _gate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        password = settings.basic_auth_password
        path = request.url.path
        gated = (
            path not in _AUTH_EXEMPT
            and not path.startswith(_AUTH_EXEMPT_PREFIXES)
            and not path.startswith(_PUBLIC_PREFIXES)
            and not path.startswith(_SESSION_GATED_PREFIXES)
        )
        if (
            password
            and request.method != "OPTIONS"
            and gated
            and not _basic_auth_ok(request.headers.get("authorization", ""), password)
        ):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="DRC Pay"'})
        return await call_next(request)

    app.state.container = build_container(
        database_url=settings.database_url,
        pawapay_base_url=settings.pawapay_base_url,
        pawapay_api_token=settings.pawapay_api_token,
        ussd_shortcode=settings.ussd_shortcode,
        pawapay_public_key=settings.pawapay_public_key,
        environment=settings.environment,
    )
    # On a live rail with no statically-set key, fetch pawaPay's callback-verification public
    # key from their API now (best-effort; a no-op on the simulator, so tests stay offline).
    app.state.container.ensure_callback_public_key()
    # The USSD channel is another thin caller into the same container/orchestrator. Menus
    # default to French (DRCPAY_USSD_LANG); the per-msisdn rate limiter lives on app.state
    # so tests get a fresh one per app.
    app.state.ussd_handler = UssdHandler(app.state.container, lang=settings.ussd_lang)
    app.state.ussd_limiter = SlidingWindowLimiter()
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(admin_merchants_router)
    app.include_router(onboarding_router)
    app.include_router(merchant_api_router)
    app.include_router(ussd_router)
    app.include_router(webhook_router)
    app.include_router(public_router)
    # Demo/ops controls (e.g. trigger reconciliation) — mounted off the real-money path only
    # (simulator or sandbox), never in production. See Container.demo_controls_enabled.
    if app.state.container.demo_controls_enabled:
        app.include_router(demo_router)

    # Hosted demo: also serve the static Merchant Console, same-origin with the API (so a
    # single Basic-auth password gates both, and there's no CORS). Off in local dev.
    if settings.console_dir:
        app.mount(
            "/console", StaticFiles(directory=settings.console_dir, html=True), name="console"
        )

        @app.get("/", include_in_schema=False)
        def _root() -> RedirectResponse:
            return RedirectResponse(url="/console/")

    # Public customer pages (scan-to-pay + USSD dial simulator) — served WITHOUT the password.
    if settings.customer_dir:
        app.mount(
            "/customer", StaticFiles(directory=settings.customer_dir, html=True), name="customer"
        )

    # Internal Staff Console (approve/reject merchant sign-ups). Mounted at /staff, not /admin:
    # /admin/* is the session-managed API (it must be reachable to log in), while this page is
    # treated like /console and stays behind the sandbox demo password. Everything it displays
    # requires an admin session regardless.
    if settings.staff_dir:
        app.mount("/staff", StaticFiles(directory=settings.staff_dir, html=True), name="staff")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
