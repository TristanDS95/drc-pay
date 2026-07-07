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
from .http.auth_routes import auth_router
from .http.demo_routes import demo_router
from .http.merchant_api import merchant_api_router
from .http.public_routes import public_router
from .http.ussd_routes import ussd_router
from .http.webhook_routes import webhook_router
from .jobs.reconciliation.sweep import run_reconciliation
from .ussd.session import UssdHandler

# The shared Basic password is now ONLY the sandbox demo's outer gate (console static files,
# docs, demo endpoints). It never gates:
#   - the pawaPay callback under /webhooks/ (verified by RFC-9421 signature instead),
#   - the platform's health probe,
#   - customer-facing paths (a customer who scans a QR has no login),
#   - the merchant API + /auth (each merchant authenticates with their OWN session — a shared
#     password would have to be handed to every merchant, defeating per-merchant auth).
#   - /demo/credentials: the login page's demo chips fetch it in the background, and some
#     browsers (Safari) don't attach cached Basic credentials to fetch() — the chips would
#     silently vanish on the hosted sandbox. Exempting it gives up nothing: the demo logins
#     are deterministic, documented in the README, and /auth/login is public anyway — the
#     list reveals nothing an outsider can't already use. (It still 404s in production;
#     /demo/reconcile and the rest of the demo shell stay gated.)
_AUTH_EXEMPT = {"/health", "/demo/credentials"}
_AUTH_EXEMPT_PREFIXES = ("/webhooks/",)
_PUBLIC_PREFIXES = ("/pay", "/ussd", "/public", "/customer")
_SESSION_GATED_PREFIXES = ("/auth", "/transactions", "/merchants", "/charges")


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


def create_app() -> FastAPI:
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

    app = FastAPI(title="DRC Pay — Merchant Acquiring API", version="0.0.1", lifespan=_lifespan)

    # DEV ONLY: let the local web Merchant Console (a different origin) call the API.
    # Production locks this down to known origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        if password and request.method != "OPTIONS" and gated:
            if not _basic_auth_ok(request.headers.get("authorization", ""), password):
                return Response(
                    status_code=401, headers={"WWW-Authenticate": 'Basic realm="DRC Pay"'}
                )
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
    # The USSD channel is another thin caller into the same container/orchestrator.
    app.state.ussd_handler = UssdHandler(app.state.container)
    app.include_router(auth_router)
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

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
