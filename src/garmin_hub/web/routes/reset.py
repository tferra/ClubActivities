"""Restablecimiento de contraseña con un código del administrador (US8)."""

from fastapi import APIRouter, Depends, Form, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.invitations import MSG_INVALID_CODE, InvalidCode
from garmin_hub.accounts.resets import redeem_reset_code
from garmin_hub.accounts.users import ValidationFailed
from garmin_hub.security.csrf import require_csrf
from garmin_hub.security.ip import client_ip, ip_prefix
from garmin_hub.security.passwords import MSG_CONFIRM_MISMATCH
from garmin_hub.security.ratelimit import Kind
from garmin_hub.web.deps import now, transaction
from garmin_hub.web.ratelimit import check_and_wait, record
from garmin_hub.web.templating import render

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.get("/restablecer")
def reset_page(request: Request) -> Response:
    return render(request, "reset.html")


def _failed(request: Request, ip: str, reason: str) -> None:
    if reason == "invalid":
        record(request, email=None, ip=ip, kind=Kind.CODE_REDEEM, succeeded=False)
    with transaction(request) as conn:
        record_event(
            conn,
            "auth.code_redeem_failed",
            actor_user_id=None,
            subject_user_id=None,
            ip_prefix=ip_prefix(ip),
            details={"kind": "reset", "reason": reason},
            now=now(request),
        )


def _redeem(request: Request, email: str, code: str, password: str) -> None:
    with transaction(request) as conn:
        redeem_reset_code(
            conn,
            email=email,
            code=code,
            new_password=password,
            keys=request.app.state.keys,
            ip_prefix=ip_prefix(client_ip(request)),
            now=now(request),
        )


@router.post("/restablecer")
async def reset_submit(
    request: Request,
    email: str = Form(""),
    code: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
) -> Response:
    ip = client_ip(request)
    context = {"email": email.strip()}
    decision = await check_and_wait(request, email=None, ip=ip, kind=Kind.CODE_REDEEM)
    if not decision.allowed:
        await run_in_threadpool(_failed, request, ip, decision.outcome.value)
        return render(request, "reset.html", {**context, "error": MSG_INVALID_CODE}, 422)
    if password != password_confirm:
        return render(request, "reset.html", {**context, "error": MSG_CONFIRM_MISMATCH}, 422)
    try:
        await run_in_threadpool(_redeem, request, email, code, password)
    except InvalidCode:
        await run_in_threadpool(_failed, request, ip, "invalid")
        return render(request, "reset.html", {**context, "error": MSG_INVALID_CODE}, 422)
    except ValidationFailed as exc:
        return render(request, "reset.html", {**context, "error": exc.message}, 422)
    return RedirectResponse("/login?restablecida=1", status_code=303)
