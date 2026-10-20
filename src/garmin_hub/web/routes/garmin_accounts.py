"""Rutas de las cuentas Garmin del usuario (specs/002-garmin-account-linking/contracts/http.md).

Las rutas solo validan formularios y llaman al dominio de `garmin_accounts`. Todo el router
exige un usuario normal (un administrador recibe 404) y CSRF en los POST. Los formularios con
errores solo conservan el alias: el correo, la contraseña y el código MFA nunca se devuelven.
"""

from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import Connection
from starlette.responses import RedirectResponse, Response

from garmin_hub.garmin.pending import PendingLogin
from garmin_hub.garmin_accounts import notice
from garmin_hub.garmin_accounts.accounts import (
    AccountRow,
    GarminActionFailed,
    GarminContext,
    Linked,
    NeedsMfa,
    can_start_link,
    cancel_mfa,
    check_account,
    complete_mfa,
    get_own_account,
    list_accounts,
    parse_account_id,
    start_link,
    start_reauth,
)
from garmin_hub.garmin_accounts.deletion import (
    AccountStepFailed,
    request_data_deletion,
    retry_deletion,
    unlink,
)
from garmin_hub.garmin_accounts.errors import MSG_DELETION_FAILED, MSG_STATE_NOT_ALLOWED
from garmin_hub.security.csrf import require_csrf
from garmin_hub.security.sessions import SessionUser
from garmin_hub.web.deps import now, request_ip_prefix, require_regular_user, transaction
from garmin_hub.web.templating import is_htmx, render

router = APIRouter(
    prefix="/cuentas-garmin",
    dependencies=[Depends(require_csrf), Depends(require_regular_user)],
)

RegularUser = Depends(require_regular_user)

STATUS_BY_KIND = {"invalid": 422, "conflict": 409, "throttled": 429, "expired": 410}


def own_account_or_404(conn: Connection, user: SessionUser, raw_id: str) -> AccountRow:
    """Misma respuesta 404 si el id no es un UUID, no existe o es de otro usuario (R15)."""
    account_id = parse_account_id(raw_id)
    account = get_own_account(conn, user.user_id, account_id) if account_id else None
    if account is None:
        raise HTTPException(status_code=404)
    return account


def garmin_context(request: Request) -> GarminContext:
    state = request.app.state
    return GarminContext(
        engine=state.engine,
        client=state.garmin_client,
        registry=state.pending_logins,
        cipher=state.token_cipher,
        settings=state.settings,
    )


def _notice_gate(request: Request, user: SessionUser, next_path: str) -> Response | None:
    """Redirige al aviso de datos si el usuario no ha aceptado la versión vigente (FR-011)."""
    with transaction(request) as conn:
        if notice.has_accepted_current(conn, user.user_id):
            return None
    return RedirectResponse(
        f"/cuentas-garmin/aviso?next={quote(next_path, safe='/')}", status_code=303
    )


def _linked_redirect(result: Linked) -> Response:
    if result.recovered:
        target = f"/cuentas-garmin?recuperada=1&cuenta={result.garmin_account_id}"
    else:
        target = "/cuentas-garmin?vinculada=1"
    return RedirectResponse(target, status_code=303)


def _mfa_page(
    request: Request, attempt: PendingLogin, error: str | None = None, status_code: int = 200
) -> Response:
    remaining = attempt.remaining_seconds(now(request))
    context = {
        "attempt_id": attempt.attempt_id,
        "remaining": f"{remaining // 60}:{remaining % 60:02d}",
        "purpose": attempt.purpose,
        "error": error,
    }
    return render(request, "garmin/mfa.html", context, status_code)


RESULT_MESSAGES = {
    "vinculada": "Cuenta Garmin vinculada.",
    "recuperada": "Se ha recuperado la cuenta con sus datos.",
    "recuperada_alias": "Se ha recuperado la cuenta «{alias}» con sus datos.",
    "reautenticada": "Cuenta Garmin autenticada de nuevo.",
    "desvinculada": "Cuenta Garmin desvinculada; sus datos se conservan.",
    "borrada": "Se han borrado la cuenta Garmin y sus datos.",
}


# --- Aviso de datos (US6, FR-011, FR-012) --------------------------------------------------

PREFIX = "/cuentas-garmin"


def safe_next(raw: str | None) -> str:
    """Solo rutas relativas bajo `/cuentas-garmin`; cualquier otra cosa vuelve al listado."""
    raw = raw or ""
    parts = urlsplit(raw)
    if (
        parts.scheme
        or parts.netloc
        or "\\" in raw
        or "//" in raw
        or not (parts.path == PREFIX or parts.path.startswith(f"{PREFIX}/"))
    ):
        return PREFIX
    return raw


@router.get("/aviso")
def notice_page(request: Request, user: SessionUser = RegularUser) -> Response:
    context = {
        "next": safe_next(request.query_params.get("next")),
        "notice_template": notice.template_name(),
    }
    return render(request, "garmin/notice.html", context)


@router.post("/aviso")
def notice_accept(
    request: Request,
    user: SessionUser = RegularUser,
    accept: str = Form(""),
    next: str = Form(""),
) -> Response:
    target = safe_next(next)
    if accept != "1":
        context = {
            "next": target,
            "notice_template": notice.template_name(),
            "error": "Marca la casilla «He leído y acepto» para continuar.",
        }
        return render(request, "garmin/notice.html", context, status_code=422)
    with transaction(request) as conn:
        notice.accept(conn, user.user_id, now(request), request_ip_prefix(request))
    return RedirectResponse(target, status_code=303)


# --- Listado (US2) --------------------------------------------------------------------------


def _list_page(
    request: Request,
    user: SessionUser,
    notice_text: str | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    with transaction(request) as conn:
        accounts = list_accounts(conn, user.user_id)
    context = {"accounts": accounts, "notice": notice_text, "error": error}
    return render(request, "garmin/list.html", context, status_code)


@router.get("")
def accounts_page(request: Request, user: SessionUser = RegularUser) -> Response:
    flag = next((f for f in RESULT_MESSAGES if request.query_params.get(f) == "1"), None)
    message = RESULT_MESSAGES.get(flag or "")
    if flag == "recuperada":
        # El alias se busca solo entre las cuentas propias (R15); si no, el mensaje genérico.
        recovered_id = parse_account_id(request.query_params.get("cuenta", ""))
        with transaction(request) as conn:
            account = get_own_account(conn, user.user_id, recovered_id) if recovered_id else None
        if account is not None:
            message = RESULT_MESSAGES["recuperada_alias"].format(alias=account.alias)
    return _list_page(request, user, message)


# --- Vinculación (US1) ----------------------------------------------------------------------


@router.get("/vincular")
def link_page(request: Request, user: SessionUser = RegularUser) -> Response:
    if redirect := _notice_gate(request, user, "/cuentas-garmin/vincular"):
        return redirect
    error = can_start_link(garmin_context(request), user.user_id)
    return render(request, "garmin/link.html", {"alias": "", "error": error}, 409 if error else 200)


@router.post("/vincular")
def link_submit(
    request: Request,
    user: SessionUser = RegularUser,
    alias: str = Form(""),
    garmin_email: str = Form(""),
    garmin_password: str = Form(""),
) -> Response:
    if redirect := _notice_gate(request, user, "/cuentas-garmin/vincular"):
        return redirect
    try:
        result = start_link(
            garmin_context(request),
            user_id=user.user_id,
            alias=alias,
            email=garmin_email.strip(),
            password=garmin_password,
            now=now(request),
            ip_prefix=request_ip_prefix(request),
        )
    except GarminActionFailed as exc:
        context = {"alias": alias.strip(), "error": exc.message}
        return render(request, "garmin/link.html", context, STATUS_BY_KIND[exc.kind])
    if isinstance(result, NeedsMfa):
        return _mfa_page(request, result.attempt)
    return _linked_redirect(result)


# --- Código MFA (US1 y US4) -----------------------------------------------------------------


@router.post("/mfa")
def mfa_submit(
    request: Request,
    user: SessionUser = RegularUser,
    attempt_id: str = Form(""),
    mfa_code: str = Form(""),
) -> Response:
    if redirect := _notice_gate(request, user, "/cuentas-garmin"):
        return redirect
    ctx = garmin_context(request)
    try:
        result = complete_mfa(
            ctx,
            user_id=user.user_id,
            attempt_id=attempt_id,
            code=mfa_code.strip(),
            now=now(request),
            ip_prefix=request_ip_prefix(request),
        )
    except GarminActionFailed as exc:
        attempt = ctx.registry.get(attempt_id, user.user_id)
        if attempt is None:
            context = {"error": exc.message}
            return render(request, "garmin/mfa_expired.html", context, status_code=410)
        return _mfa_page(request, attempt, exc.message, STATUS_BY_KIND[exc.kind])
    if isinstance(result, Linked):
        return _linked_redirect(result)
    return RedirectResponse("/cuentas-garmin?reautenticada=1", status_code=303)


@router.post("/mfa/cancelar")
def mfa_cancel(
    request: Request, user: SessionUser = RegularUser, attempt_id: str = Form("")
) -> Response:
    cancel_mfa(garmin_context(request), user_id=user.user_id, attempt_id=attempt_id)
    return RedirectResponse("/cuentas-garmin", status_code=303)


# --- Reautenticación (US4) ------------------------------------------------------------------


def _reauth_page(
    request: Request, account: AccountRow, error: str | None = None, status_code: int = 200
) -> Response:
    return render(request, "garmin/reauth.html", {"account": account, "error": error}, status_code)


@router.get("/{account_id}/reautenticar")
def reauth_page(request: Request, account_id: str, user: SessionUser = RegularUser) -> Response:
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    if redirect := _notice_gate(
        request, user, f"/cuentas-garmin/{account.garmin_account_id}/reautenticar"
    ):
        return redirect
    if not account.is_active:
        return _reauth_page(request, account, MSG_STATE_NOT_ALLOWED, 409)
    return _reauth_page(request, account)


@router.post("/{account_id}/reautenticar")
def reauth_submit(
    request: Request,
    account_id: str,
    user: SessionUser = RegularUser,
    garmin_email: str = Form(""),
    garmin_password: str = Form(""),
) -> Response:
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    if redirect := _notice_gate(
        request, user, f"/cuentas-garmin/{account.garmin_account_id}/reautenticar"
    ):
        return redirect
    try:
        result = start_reauth(
            garmin_context(request),
            user_id=user.user_id,
            account_id=account.garmin_account_id,
            email=garmin_email.strip(),
            password=garmin_password,
            now=now(request),
            ip_prefix=request_ip_prefix(request),
        )
    except GarminActionFailed as exc:
        return _reauth_page(request, account, exc.message, STATUS_BY_KIND[exc.kind])
    if isinstance(result, NeedsMfa):
        return _mfa_page(request, result.attempt)
    return RedirectResponse("/cuentas-garmin?reautenticada=1", status_code=303)


# --- Desvinculación y borrado (US5) ---------------------------------------------------------


def _deletion_failed(request: Request, user: SessionUser) -> Response:
    """500 controlado: la cuenta sigue en `deleting` y el listado ofrece "Reintentar" (FR-022)."""
    return _list_page(request, user, error=MSG_DELETION_FAILED, status_code=500)


@router.get("/{account_id}/desvincular")
def unlink_page(request: Request, account_id: str, user: SessionUser = RegularUser) -> Response:
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    if not account.is_active:
        context = {"account": account, "error": MSG_STATE_NOT_ALLOWED}
        return render(request, "garmin/unlink.html", context, status_code=409)
    return render(request, "garmin/unlink.html", {"account": account})


@router.post("/{account_id}/desvincular")
def unlink_submit(
    request: Request,
    account_id: str,
    user: SessionUser = RegularUser,
    mode: str = Form(""),
    confirmation: str = Form(""),
) -> Response:
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    try:
        done = unlink(
            garmin_context(request),
            user_id=user.user_id,
            account_id=account.garmin_account_id,
            mode=mode,
            confirmation=confirmation,
            now=now(request),
            ip_prefix=request_ip_prefix(request),
        )
    except GarminActionFailed as exc:
        context = {"account": account, "error": exc.message}
        return render(request, "garmin/unlink.html", context, STATUS_BY_KIND[exc.kind])
    except AccountStepFailed:
        return _deletion_failed(request, user)
    flag = "desvinculada" if done == "keep" else "borrada"
    return RedirectResponse(f"/cuentas-garmin?{flag}=1", status_code=303)


@router.get("/{account_id}/borrar-datos")
def delete_data_page(
    request: Request, account_id: str, user: SessionUser = RegularUser
) -> Response:
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    if account.status != "unlinked":
        context = {"account": account, "error": MSG_STATE_NOT_ALLOWED}
        return render(request, "garmin/delete_data.html", context, status_code=409)
    return render(request, "garmin/delete_data.html", {"account": account})


@router.post("/{account_id}/borrar-datos")
def delete_data_submit(
    request: Request,
    account_id: str,
    user: SessionUser = RegularUser,
    confirmation: str = Form(""),
) -> Response:
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    try:
        request_data_deletion(
            garmin_context(request),
            user_id=user.user_id,
            account_id=account.garmin_account_id,
            confirmation=confirmation,
            now=now(request),
            ip_prefix=request_ip_prefix(request),
        )
    except GarminActionFailed as exc:
        context = {"account": account, "error": exc.message}
        return render(request, "garmin/delete_data.html", context, STATUS_BY_KIND[exc.kind])
    except AccountStepFailed:
        return _deletion_failed(request, user)
    return RedirectResponse("/cuentas-garmin?borrada=1", status_code=303)


@router.post("/{account_id}/reintentar-borrado")
def delete_retry(request: Request, account_id: str, user: SessionUser = RegularUser) -> Response:
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    try:
        retry_deletion(
            garmin_context(request),
            user_id=user.user_id,
            account_id=account.garmin_account_id,
            now=now(request),
            ip_prefix=request_ip_prefix(request),
        )
    except GarminActionFailed as exc:
        return _list_page(request, user, error=exc.message, status_code=409)
    except AccountStepFailed:
        return _deletion_failed(request, user)
    return RedirectResponse("/cuentas-garmin?borrada=1", status_code=303)


# --- Comprobación (US7) ---------------------------------------------------------------------


@router.post("/{account_id}/comprobar")
def check_submit(request: Request, account_id: str, user: SessionUser = RegularUser) -> Response:
    """Devuelve la fila actualizada (fragmento HTMX) con el resultado; sin HTMX, el listado."""
    with transaction(request) as conn:
        account = own_account_or_404(conn, user, account_id)
    status_code = 200
    message = error = None
    try:
        outcome = check_account(
            garmin_context(request),
            user_id=user.user_id,
            account_id=account.garmin_account_id,
            now=now(request),
            ip_prefix=request_ip_prefix(request),
        )
    except GarminActionFailed as exc:
        error, status_code = exc.message, STATUS_BY_KIND[exc.kind]
    else:
        if outcome.ok:
            message = outcome.message
        else:
            error = outcome.message
    if not is_htmx(request):
        return _list_page(request, user, message, error, status_code)
    with transaction(request) as conn:
        current = get_own_account(conn, user.user_id, account.garmin_account_id) or account
    context = {"a": current, "row_message": message, "row_error": error}
    return render(request, "garmin/_row.html", context, status_code)
