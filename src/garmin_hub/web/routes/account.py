"""Rutas del propio usuario: inicio, cuenta, exportación y borrado."""

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from garmin_hub.accounts.deletion import (
    DeletionContext,
    StepFailed,
    execute_deletion,
    request_self_deletion,
)
from garmin_hub.accounts.export import build_export
from garmin_hub.accounts.users import (
    Conflict,
    ValidationFailed,
    change_display_name,
    change_password,
    get_user,
)
from garmin_hub.security.csrf import require_csrf
from garmin_hub.security.ip import client_ip
from garmin_hub.security.passwords import MSG_CONFIRM_MISMATCH
from garmin_hub.security.sessions import COOKIE_ATTRS, COOKIE_NAME, SessionUser
from garmin_hub.web.deps import now, request_ip_prefix, require_user, transaction
from garmin_hub.web.templating import render

router = APIRouter(dependencies=[Depends(require_csrf)])

CurrentUser = Depends(require_user)

NOTICES = {
    "nombre": "Nombre actualizado.",
    "contrasena": "Contraseña cambiada; se han cerrado tus demás sesiones.",
}


@router.get("/")
def home(request: Request, user: SessionUser = CurrentUser) -> Response:
    return render(request, "home.html")


def _account_page(
    request: Request, user: SessionUser, status_code: int = 200, **context: object
) -> Response:
    with transaction(request) as conn:
        profile = get_user(conn, user.user_id)
    return render(request, "account.html", {"profile": profile, **context}, status_code)


@router.get("/cuenta")
def account(request: Request, user: SessionUser = CurrentUser) -> Response:
    notice = NOTICES.get(request.query_params.get("ok", ""))
    return _account_page(request, user, notice=notice)


@router.post("/cuenta/nombre")
def account_name(
    request: Request, user: SessionUser = CurrentUser, display_name: str = Form("")
) -> Response:
    try:
        with transaction(request) as conn:
            change_display_name(
                conn,
                user.user_id,
                display_name,
                ip_prefix=request_ip_prefix(request),
                now=now(request),
            )
    except ValidationFailed as exc:
        return _account_page(request, user, 422, name_error=exc.message)
    return RedirectResponse("/cuenta?ok=nombre", status_code=303)


@router.post("/cuenta/contrasena")
def account_password(
    request: Request,
    user: SessionUser = CurrentUser,
    current_password: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
) -> Response:
    if password != password_confirm:
        return _account_page(request, user, 422, password_error=MSG_CONFIRM_MISMATCH)
    state = request.app.state
    with transaction(request) as conn:
        result = change_password(
            conn,
            user_id=user.user_id,
            current_password=current_password,
            new_password=password,
            current_session_hash=user.session_hash,
            ip=client_ip(request),
            keys=state.keys,
            settings=state.settings,
            now=now(request),
        )
    if result.error:
        return _account_page(request, user, 422, password_error=result.error)
    return RedirectResponse("/cuenta?ok=contrasena", status_code=303)


@router.get("/cuenta/exportar")
def account_export(request: Request, user: SessionUser = CurrentUser) -> Response:
    with transaction(request) as conn:
        data = build_export(
            conn, user.user_id, ip_prefix=request_ip_prefix(request), now=now(request)
        )
    return JSONResponse(
        data,
        headers={"Content-Disposition": 'attachment; filename="garmin-hub-export.json"'},
    )


@router.get("/cuenta/eliminar")
def account_delete_page(request: Request, user: SessionUser = CurrentUser) -> Response:
    return render(request, "account_delete.html")


@router.post("/cuenta/eliminar")
def account_delete(
    request: Request,
    user: SessionUser = CurrentUser,
    current_password: str = Form(""),
    confirmation: str = Form(""),
) -> Response:
    state = request.app.state
    try:
        with transaction(request) as conn:
            error = request_self_deletion(
                conn,
                user_id=user.user_id,
                current_password=current_password,
                confirmation=confirmation,
                ip=client_ip(request),
                keys=state.keys,
                settings=state.settings,
                now=now(request),
            )
    except Conflict as exc:
        return render(request, "account_delete.html", {"error": exc.message}, status_code=409)
    if error:
        return render(request, "account_delete.html", {"error": error}, status_code=422)
    target = "/login?eliminada=1"
    try:
        execute_deletion(
            DeletionContext(engine=state.engine, now=now(request)),
            user.user_id,
            ip_prefix=request_ip_prefix(request),
        )
    except StepFailed:
        target = "/login?borrado_pendiente=1"
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(COOKIE_NAME, **COOKIE_ATTRS)
    return response
