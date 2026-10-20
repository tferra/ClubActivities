"""Inicio y cierre de sesión (US4)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.users import MSG_LOGIN_FAILED, AuthFailure, authenticate, normalize_email
from garmin_hub.security.csrf import require_csrf
from garmin_hub.security.ip import client_ip, ip_prefix
from garmin_hub.security.ratelimit import Decision, Kind, purge_old_attempts
from garmin_hub.security.sessions import (
    COOKIE_ATTRS,
    COOKIE_NAME,
    create_session,
    delete_session,
    purge_expired_sessions,
)
from garmin_hub.web.deps import current_user, now, transaction
from garmin_hub.web.ratelimit import check_and_wait
from garmin_hub.web.templating import render

router = APIRouter(dependencies=[Depends(require_csrf)])

NOTICES = {
    "restablecida": "Contraseña restablecida. Ya puedes iniciar sesión.",
    "eliminada": "Tu usuario y todos sus datos se han eliminado.",
    "borrado_pendiente": (
        "Tu acceso está cerrado, pero el borrado de tus datos no se ha completado; "
        "el administrador lo terminará."
    ),
}


@router.get("/login")
def login_page(request: Request) -> Response:
    notice = next((text for key, text in NOTICES.items() if request.query_params.get(key)), None)
    return render(request, "login.html", {"notice": notice})


def _login(request: Request, email: str, password: str, decision: Decision) -> str | None:
    """Autentica y, si va bien, crea la sesión; devuelve su id en claro."""
    state = request.app.state
    with transaction(request) as conn:
        result = authenticate(
            conn,
            email=email,
            password=password,
            ip=client_ip(request),
            decision=decision,
            keys=state.keys,
            settings=state.settings,
            now=now(request),
        )
        if isinstance(result, AuthFailure):
            return None
        assert isinstance(result, UUID)  # noqa: S101
        purge_expired_sessions(conn, state.settings, now(request))
        purge_old_attempts(conn, now(request))
        return create_session(conn, result, state.keys, state.settings, now(request))


@router.post("/login")
async def login_submit(
    request: Request, email: str = Form(""), password: str = Form("")
) -> Response:
    ip = client_ip(request)
    decision = await check_and_wait(request, email=normalize_email(email), ip=ip, kind=Kind.LOGIN)
    session_id = await run_in_threadpool(_login, request, email, password, decision)
    if session_id is None:
        # No se devuelve el correo: la respuesta debe ser idéntica exista o no (SC-005).
        return render(request, "login.html", {"error": MSG_LOGIN_FAILED}, status_code=422)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE_NAME, session_id, **COOKIE_ATTRS)
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    user = current_user(request)
    if user is not None:
        with transaction(request) as conn:
            delete_session(conn, user.session_id, request.app.state.keys)
            record_event(
                conn,
                "auth.logout",
                actor_user_id=user.user_id,
                subject_user_id=user.user_id,
                ip_prefix=ip_prefix(client_ip(request)),
                now=now(request),
            )
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, **COOKIE_ATTRS)
    return response
