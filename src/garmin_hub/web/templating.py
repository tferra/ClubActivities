"""Renderizado de plantillas con el token CSRF y el usuario en el contexto."""

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from garmin_hub.garmin_accounts.errors import ERROR_CODE_MESSAGES
from garmin_hub.security.csrf import ANON_COOKIE, new_anon_pair, session_token
from garmin_hub.security.csrf import anon_token as _anon_token
from garmin_hub.security.sessions import COOKIE_ATTRS

TEMPLATES_DIR = Path(__file__).parent / "templates"

STATUS_LABELS = {
    "active": "Activo",
    "deactivated": "Desactivado",
    "pending_deletion": "Borrado pendiente",
}
ROLE_LABELS = {"user": "Usuario", "admin": "Administrador"}
# Etiquetas de estado de las cuentas Garmin (feature 002, contracts/http.md).
GARMIN_STATUS_LABELS = {
    "valid": "Válida",
    "reauth_required": "Requiere reautenticación",
    "error": "Error",
    "unlinked": "Desvinculada (datos conservados)",
    "deleting": "Borrando datos… (no se pudo completar)",
}


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    templates.env.filters["dt"] = lambda value: (
        value.strftime("%Y-%m-%d %H:%M UTC") if value else "—"
    )
    templates.env.filters["dt_or_never"] = lambda value: (
        value.strftime("%Y-%m-%d %H:%M UTC") if value else "Nunca"
    )
    templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
    templates.env.globals["ROLE_LABELS"] = ROLE_LABELS
    templates.env.globals["GARMIN_STATUS_LABELS"] = GARMIN_STATUS_LABELS
    templates.env.globals["GARMIN_ERROR_MESSAGES"] = ERROR_CODE_MESSAGES
    return templates


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> Response:
    """Renderiza `name`; si no hay sesión, prepara el doble envío CSRF anónimo."""
    state = request.app.state
    user = getattr(request.state, "user", None)
    new_nonce = None
    if user is not None:
        token = session_token(state.keys, user.session_id)
    else:
        nonce = request.cookies.get(ANON_COOKIE)
        if nonce:
            token = _anon_token(state.keys, nonce)
        else:
            new_nonce, token = new_anon_pair(state.keys)
    ctx = {"user": user, "csrf_token": token, **(context or {})}
    response = state.templates.TemplateResponse(request, name, ctx, status_code=status_code)
    if new_nonce is not None:
        response.set_cookie(ANON_COOKIE, new_nonce, **COOKIE_ATTRS)
    return response


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"
