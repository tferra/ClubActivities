"""Dependencias comunes de las rutas (research R8, R9 y R11)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Connection

from garmin_hub.security.csrf import require_csrf
from garmin_hub.security.ip import client_ip, ip_prefix
from garmin_hub.security.sessions import COOKIE_NAME, SessionUser, resolve_session

__all__ = [
    "LoginRequired",
    "client_ip",
    "current_user",
    "now",
    "request_ip_prefix",
    "require_admin",
    "require_csrf",
    "require_user",
    "transaction",
]


_MISSING = object()


class LoginRequired(Exception):
    """La ruta necesita una sesión válida."""


@contextmanager
def transaction(request: Request) -> Iterator[Connection]:
    """Una transacción explícita; se confirma al salir del bloque, antes de responder."""
    with request.app.state.engine.begin() as conn:
        yield conn


def now(request: Request) -> datetime:
    return request.app.state.clock()


def request_ip_prefix(request: Request) -> str:
    return ip_prefix(client_ip(request))


def current_user(request: Request) -> SessionUser | None:
    """Resuelve la sesión de la cookie una sola vez por petición."""
    cached = getattr(request.state, "user", _MISSING)
    if cached is not _MISSING:
        return cached
    user = None
    raw_id = request.cookies.get(COOKIE_NAME)
    if raw_id:
        state = request.app.state
        with transaction(request) as conn:
            user = resolve_session(conn, raw_id, state.keys, state.settings, now(request))
    request.state.user = user
    request.state.authenticated = user is not None
    return user


def require_user(request: Request) -> SessionUser:
    user = current_user(request)
    if user is None:
        raise LoginRequired
    return user


def require_admin(user: SessionUser = Depends(require_user)) -> SessionUser:  # noqa: B008
    if not user.is_admin:
        raise HTTPException(status_code=404)
    return user
