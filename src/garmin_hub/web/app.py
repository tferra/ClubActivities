"""Aplicación FastAPI de garmin-hub."""

import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from garmin_hub.clock import utc_now
from garmin_hub.config import Settings
from garmin_hub.db.engine import create_engine_from
from garmin_hub.garmin.client import GarminClient
from garmin_hub.garmin.pending import PendingLoginRegistry
from garmin_hub.keys import derive_keys
from garmin_hub.logging_setup import AccessLogMiddleware
from garmin_hub.secrets import Secrets
from garmin_hub.security.csrf import CsrfError
from garmin_hub.security.headers import SecurityHeadersMiddleware
from garmin_hub.security.sessions import COOKIE_ATTRS, COOKIE_NAME
from garmin_hub.security.token_cipher import TokenCipher, parse_master_keys
from garmin_hub.web.deps import LoginRequired
from garmin_hub.web.templating import build_templates, render

logger = logging.getLogger("garmin_hub.web")

STATIC_DIR = Path(__file__).parent / "static"

HTTP_MESSAGES = {
    400: "La petición no es válida.",
    405: "Método no permitido.",
    413: "La petición es demasiado grande.",
}

type Sleep = Callable[[float], Awaitable[Any]]


def create_app(
    settings: Settings,
    secrets: Secrets,
    *,
    engine: Engine | None = None,
    clock: Callable[[], datetime] = utc_now,
    sleep: Sleep = anyio.sleep,
    garmin_client: GarminClient | None = None,
) -> FastAPI:
    # Registros ampliables de la feature 002 (pasos de borrado y secciones de exportación).
    import garmin_hub.garmin_accounts.deletion
    import garmin_hub.garmin_accounts.export  # noqa: F401

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.keys = derive_keys(secrets.session_secret)
    app.state.engine = engine if engine is not None else create_engine_from(secrets, settings)
    app.state.clock = clock
    app.state.sleep = sleep
    app.state.templates = build_templates()
    app.state.rng = random.Random()  # noqa: S311 - jitter, no criptografía
    app.state.token_cipher = TokenCipher(parse_master_keys(secrets.master_keys))
    app.state.garmin_client = (
        garmin_client if garmin_client is not None else build_garmin_client(settings)
    )
    app.state.pending_logins = PendingLoginRegistry(
        ttl=timedelta(minutes=settings.garmin_mfa_ttl_minutes),
        clock=clock,
        client=app.state.garmin_client,
    )

    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_https)
    app.add_middleware(AccessLogMiddleware)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    _register_error_handlers(app)
    _register_routers(app)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return app


def build_garmin_client(settings: Settings) -> GarminClient:
    """`FakeGarminClient` solo con `GARMIN_HUB_GARMIN_CLIENT=fake` (dev/test, research R18)."""
    if settings.garmin_client == "fake":
        from garmin_hub.garmin.fake import FakeGarminClient

        return FakeGarminClient()
    from garmin_hub.garmin.garminconnect_client import GarminConnectClient

    return GarminConnectClient(
        max_retries=settings.garmin_max_retries,
        login_max_retries=settings.garmin_login_max_retries,
        strategy_pause=settings.garmin_login_strategy_pause_seconds,
        login_budget=settings.garmin_login_budget_seconds,
    )


def route_modules() -> tuple[ModuleType, ...]:
    from garmin_hub.web.routes import account, admin, auth, garmin_accounts, reset, signup

    return (auth, signup, reset, account, admin, garmin_accounts)


def _register_routers(app: FastAPI) -> None:
    # Cada router declara `require_csrf` como dependencia propia (research R9).
    for module in route_modules():
        app.include_router(module.router)


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired) -> Response:
        if request.headers.get("hx-request") == "true":
            response: Response = Response(status_code=200, headers={"HX-Redirect": "/login"})
        else:
            response = RedirectResponse("/login", status_code=303)
        if request.cookies.get(COOKIE_NAME):
            response.delete_cookie(COOKIE_NAME, **COOKIE_ATTRS)
        return response

    @app.exception_handler(CsrfError)
    async def csrf_error(request: Request, exc: CsrfError) -> Response:
        return render(request, "errors/csrf.html", status_code=403)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404:
            return render(request, "errors/404.html", status_code=404)
        message = HTTP_MESSAGES.get(exc.status_code, "La petición no se ha podido atender.")
        return PlainTextResponse(message, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        return PlainTextResponse("La petición no es válida.", status_code=422)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled error", extra={"path": request.url.path})
        return render(request, "errors/500.html", status_code=500)


def app_from_env() -> FastAPI:
    """Factoría para `uvicorn --reload` (solo desarrollo)."""
    from garmin_hub.cli.main import bootstrap

    runtime = bootstrap()
    return create_app(runtime.settings, runtime.secrets)
