"""Alta con código de invitación (US3)."""

from fastapi import APIRouter, Depends, Form, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.invitations import (
    MSG_INVALID_CODE,
    InvalidCode,
    PendingInvitation,
    peek_invitation,
    redeem_invitation,
)
from garmin_hub.accounts.users import ValidationFailed, normalize_email
from garmin_hub.security.csrf import require_csrf
from garmin_hub.security.ip import client_ip, ip_prefix
from garmin_hub.security.passwords import MSG_CONFIRM_MISMATCH
from garmin_hub.security.ratelimit import Kind
from garmin_hub.security.sessions import COOKIE_ATTRS, COOKIE_NAME, create_session
from garmin_hub.web.deps import now, transaction
from garmin_hub.web.ratelimit import check_and_wait, record
from garmin_hub.web.templating import render

router = APIRouter(dependencies=[Depends(require_csrf)])


def _code_failed(request: Request, ip: str, reason: str) -> None:
    """Registra el fallo de canje (cuenta para el límite por origen) y su auditoría."""
    if reason == "invalid":
        record(request, email=None, ip=ip, kind=Kind.CODE_REDEEM, succeeded=False)
    with transaction(request) as conn:
        record_event(
            conn,
            "auth.code_redeem_failed",
            actor_user_id=None,
            subject_user_id=None,
            ip_prefix=ip_prefix(ip),
            details={"kind": "invitation", "reason": reason},
            now=now(request),
        )


def _generic(request: Request) -> Response:
    return render(request, "signup_code.html", {"error": MSG_INVALID_CODE}, status_code=422)


@router.get("/alta")
def signup_page(request: Request) -> Response:
    return render(request, "signup_code.html")


def _peek(request: Request, code: str) -> PendingInvitation | None:
    with transaction(request) as conn:
        return peek_invitation(conn, code, request.app.state.keys, now(request))


@router.post("/alta/codigo")
async def signup_code(request: Request, code: str = Form("")) -> Response:
    ip = client_ip(request)
    decision = await check_and_wait(request, email=None, ip=ip, kind=Kind.CODE_REDEEM)
    if not decision.allowed:
        await run_in_threadpool(_code_failed, request, ip, decision.outcome.value)
        return _generic(request)
    pending = await run_in_threadpool(_peek, request, code)
    if pending is None:
        await run_in_threadpool(_code_failed, request, ip, "invalid")
        return _generic(request)
    return render(request, "signup_details.html", {"code": code, "email": pending.email})


def _redeem(request: Request, code: str, display_name: str, password: str) -> str:
    """Canjea el código y abre la sesión; devuelve el id de sesión en claro."""
    state = request.app.state
    with transaction(request) as conn:
        user_id = redeem_invitation(
            conn,
            code=code,
            display_name=display_name,
            password=password,
            keys=state.keys,
            ip_prefix=ip_prefix(client_ip(request)),
            now=now(request),
        )
        return create_session(conn, user_id, state.keys, state.settings, now(request))


@router.post("/alta")
async def signup_submit(
    request: Request,
    code: str = Form(""),
    display_name: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    email: str | None = Form(None),
) -> Response:
    ip = client_ip(request)
    decision = await check_and_wait(request, email=None, ip=ip, kind=Kind.CODE_REDEEM)
    if not decision.allowed:
        await run_in_threadpool(_code_failed, request, ip, decision.outcome.value)
        return _generic(request)
    pending = await run_in_threadpool(_peek, request, code)
    if pending is None or (email is not None and normalize_email(email) != pending.email):
        await run_in_threadpool(_code_failed, request, ip, "invalid")
        return _generic(request)
    details = {"code": code, "email": pending.email, "display_name": display_name}
    if password != password_confirm:
        details["error"] = MSG_CONFIRM_MISMATCH
        return render(request, "signup_details.html", details, status_code=422)
    try:
        session_id = await run_in_threadpool(_redeem, request, code, display_name, password)
    except ValidationFailed as exc:
        details["error"] = exc.message
        return render(request, "signup_details.html", details, status_code=422)
    except InvalidCode:
        await run_in_threadpool(_code_failed, request, ip, "invalid")
        return _generic(request)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE_NAME, session_id, **COOKIE_ATTRS)
    return response
