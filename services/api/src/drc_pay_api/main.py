"""FastAPI application factory.

Thin HTTP layer: routing, middleware, and serialization only. All money logic lives
in ``drc_pay_api.domains``, framework-agnostic, so the same core can later be driven
by the USSD gateway without reimplementation.

``create_app()`` builds a fresh application (with its own in-memory wiring), so tests
spin up isolated instances. The module-level ``app`` is what uvicorn serves.
"""
from __future__ import annotations

import base64
import secrets
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .http.container import build_container
from .http.demo_routes import demo_router
from .http.merchant_api import merchant_api_router
from .http.public_routes import public_router
from .http.ussd_routes import ussd_router
from .http.webhook_routes import webhook_router
from .ussd.session import UssdHandler

# Paths reachable WITHOUT the shared password: pawaPay's signed webhook (it can't send our
# password — it's verified by signature instead) and the platform's health probe.
_AUTH_EXEMPT = {"/health", "/webhooks/pawapay"}
# Customer-facing paths are public — a customer who scans a merchant's QR has no login.
_PUBLIC_PREFIXES = ("/pay", "/ussd", "/public", "/customer")


def _basic_auth_ok(authorization: str, password: str) -> bool:
    if not authorization.startswith("Basic "):
        return False
    try:
        user, _, supplied = base64.b64decode(authorization[6:]).decode().partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return secrets.compare_digest(user, "drcpay") and secrets.compare_digest(supplied, password)


def create_app() -> FastAPI:
    app = FastAPI(title="DRC Pay — Merchant Acquiring API", version="0.0.1")

    # DEV ONLY: let the local web Merchant Console (a different origin) call the API.
    # Production locks this down to known origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Optional shared-password gate for a hosted sandbox demo. Off when no password is set
    # (local dev / tests). Exempts the webhook + health paths and CORS preflights.
    @app.middleware("http")
    async def _gate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        password = settings.basic_auth_password
        path = request.url.path
        gated = path not in _AUTH_EXEMPT and not path.startswith(_PUBLIC_PREFIXES)
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
