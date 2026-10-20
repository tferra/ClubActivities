"""Rutas de administración (`/admin/**`, 404 para quien no es administrador)."""

import contextlib
from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import Connection
from starlette.responses import RedirectResponse, Response

from garmin_hub.accounts.deletion import (
    DeletionContext,
    StepFailed,
    check_admin_deletable,
    check_retryable,
    execute_deletion,
    request_admin_deletion,
)
from garmin_hub.accounts.invitations import (
    create_invitation,
    list_invitations,
    revoke_invitation,
)
from garmin_hub.accounts.resets import create_reset_code
from garmin_hub.accounts.users import (
    Conflict,
    NotFound,
    UserRow,
    ValidationFailed,
    deactivate_user,
    get_user,
    list_users,
    reactivate_user,
)
from garmin_hub.security.csrf import require_csrf
from garmin_hub.security.sessions import SessionUser
from garmin_hub.web.deps import now, request_ip_prefix, require_admin, transaction
from garmin_hub.web.templating import is_htmx, render

router = APIRouter(prefix="/admin", dependencies=[Depends(require_csrf)])

AdminUser = Depends(require_admin)


def _parse_ttl(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return -1


@router.get("/invitaciones")
def invitations_page(request: Request, admin: SessionUser = AdminUser) -> Response:
    with transaction(request) as conn:
        invitations = list_invitations(conn, now(request))
    return render(request, "admin/invitations.html", {"invitations": invitations})


@router.post("/invitaciones")
def invitations_create(
    request: Request,
    admin: SessionUser = AdminUser,
    email: str = Form(""),
    note: str = Form(""),
    ttl_days: str = Form(""),
) -> Response:
    state = request.app.state
    try:
        with transaction(request) as conn:
            _, code = create_invitation(
                conn,
                admin_id=admin.user_id,
                email=email,
                note=note,
                ttl_days=_parse_ttl(ttl_days),
                ip_prefix=request_ip_prefix(request),
                keys=state.keys,
                settings=state.settings,
                now=now(request),
            )
    except ValidationFailed as exc:
        context = {"form_error": exc.message, "form": {"email": email, "note": note}}
        if is_htmx(request):
            return render(request, "admin/_invitation_error.html", context, status_code=422)
        with transaction(request) as conn:
            context["invitations"] = list_invitations(conn, now(request))
        return render(request, "admin/invitations.html", context, status_code=422)
    with transaction(request) as conn:
        invitations = list_invitations(conn, now(request))
    context = {"code": code, "email": email.strip().lower(), "invitations": invitations}
    if is_htmx(request):
        return render(request, "admin/_invitation_created.html", context)
    return render(request, "admin/invitations.html", context)


def parse_id(value: str) -> UUID:
    """Un identificador mal formado se trata como inexistente (404)."""
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=404) from None


@router.get("/usuarios")
def users_page(request: Request, admin: SessionUser = AdminUser) -> Response:
    with transaction(request) as conn:
        users = list_users(conn)
    return render(request, "admin/users.html", {"users": users})


def _user_action(
    request: Request,
    admin: SessionUser,
    user_id: str,
    action: Callable[..., UserRow],
) -> Response:
    uid = parse_id(user_id)
    try:
        with transaction(request) as conn:
            row = action(
                conn,
                admin_id=admin.user_id,
                user_id=uid,
                ip_prefix=request_ip_prefix(request),
                now=now(request),
            )
    except NotFound:
        raise HTTPException(status_code=404) from None
    except Conflict as exc:
        return _user_row_response(request, uid, error=exc.message, status_code=409)
    return _user_row_response(request, row.user_id, row=row)


def _user_row_response(
    request: Request,
    user_id: UUID,
    *,
    row: UserRow | None = None,
    error: str | None = None,
    status_code: int = 200,
    extra: dict[str, object] | None = None,
) -> Response:
    if not is_htmx(request):
        if error:
            with transaction(request) as conn:
                users = list_users(conn)
            return render(
                request, "admin/users.html", {"users": users, "error": error}, status_code
            )
        return RedirectResponse("/admin/usuarios", status_code=303)
    if row is None:
        with transaction(request) as conn:
            row = _get_user_or_404(conn, user_id)
    context = {"u": row, "row_error": error, **(extra or {})}
    return render(request, "admin/_user_row.html", context, status_code)


def _get_user_or_404(conn: Connection, user_id: UUID) -> UserRow:
    try:
        return get_user(conn, user_id)
    except NotFound:
        raise HTTPException(status_code=404) from None


@router.post("/usuarios/{user_id}/desactivar")
def user_deactivate(request: Request, user_id: str, admin: SessionUser = AdminUser) -> Response:
    return _user_action(request, admin, user_id, deactivate_user)


@router.post("/usuarios/{user_id}/reactivar")
def user_reactivate(request: Request, user_id: str, admin: SessionUser = AdminUser) -> Response:
    return _user_action(request, admin, user_id, reactivate_user)


@router.post("/invitaciones/{invitation_id}/revocar")
def invitation_revoke(
    request: Request, invitation_id: str, admin: SessionUser = AdminUser
) -> Response:
    iid = parse_id(invitation_id)
    try:
        with transaction(request) as conn:
            inv = revoke_invitation(
                conn,
                admin_id=admin.user_id,
                invitation_id=iid,
                ip_prefix=request_ip_prefix(request),
                now=now(request),
            )
    except NotFound:
        raise HTTPException(status_code=404) from None
    except Conflict as exc:
        if not is_htmx(request):
            with transaction(request) as conn:
                invitations = list_invitations(conn, now(request))
            context = {"invitations": invitations, "error": exc.message}
            return render(request, "admin/invitations.html", context, status_code=409)
        return render(request, "admin/_invitation_error.html", {"form_error": exc.message}, 409)
    if not is_htmx(request):
        return RedirectResponse("/admin/invitaciones", status_code=303)
    return render(request, "admin/_invitation_row.html", {"inv": inv})


@router.get("/usuarios/{user_id}/eliminar")
def user_delete_page(request: Request, user_id: str, admin: SessionUser = AdminUser) -> Response:
    uid = parse_id(user_id)
    try:
        with transaction(request) as conn:
            target = check_admin_deletable(conn, uid)
    except NotFound:
        raise HTTPException(status_code=404) from None
    except Conflict as exc:
        return render(request, "admin/user_delete.html", {"error": exc.message}, 409)
    return render(request, "admin/user_delete.html", {"target": target})


@router.post("/usuarios/{user_id}/eliminar")
def user_delete(
    request: Request,
    user_id: str,
    admin: SessionUser = AdminUser,
    confirmation_email: str = Form(""),
) -> Response:
    uid = parse_id(user_id)
    try:
        with transaction(request) as conn:
            request_admin_deletion(
                conn,
                admin_id=admin.user_id,
                user_id=uid,
                confirmation_email=confirmation_email,
                ip_prefix=request_ip_prefix(request),
                now=now(request),
            )
    except NotFound:
        raise HTTPException(status_code=404) from None
    except Conflict as exc:
        return render(request, "admin/user_delete.html", {"error": exc.message}, 409)
    except ValidationFailed as exc:
        with transaction(request) as conn:
            target = get_user(conn, uid)
        context = {"target": target, "error": exc.message}
        return render(request, "admin/user_delete.html", context, 422)
    # Si un paso falla, el usuario queda en "Borrado pendiente" con la acción "Reintentar".
    with contextlib.suppress(StepFailed):
        execute_deletion(
            DeletionContext(engine=request.app.state.engine, now=now(request)),
            uid,
            ip_prefix=request_ip_prefix(request),
        )
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.post("/usuarios/{user_id}/reintentar-borrado")
def user_delete_retry(request: Request, user_id: str, admin: SessionUser = AdminUser) -> Response:
    uid = parse_id(user_id)
    try:
        with transaction(request) as conn:
            check_retryable(conn, uid)
    except NotFound:
        raise HTTPException(status_code=404) from None
    except Conflict as exc:
        return _user_row_response(request, uid, error=exc.message, status_code=409)
    try:
        execute_deletion(
            DeletionContext(engine=request.app.state.engine, now=now(request)),
            uid,
            ip_prefix=request_ip_prefix(request),
        )
    except StepFailed as exc:
        error = f"El paso de borrado «{exc.step}» ha vuelto a fallar."
        return _user_row_response(request, uid, error=error, status_code=409)
    if not is_htmx(request):
        return RedirectResponse("/admin/usuarios", status_code=303)
    return Response(status_code=200)  # la fila desaparece (hx-swap="outerHTML")


@router.post("/usuarios/{user_id}/restablecimiento")
def user_reset_code(request: Request, user_id: str, admin: SessionUser = AdminUser) -> Response:
    uid = parse_id(user_id)
    state = request.app.state
    try:
        with transaction(request) as conn:
            code = create_reset_code(
                conn,
                admin_id=admin.user_id,
                user_id=uid,
                keys=state.keys,
                settings=state.settings,
                ip_prefix=request_ip_prefix(request),
                now=now(request),
            )
            target = get_user(conn, uid)
    except NotFound:
        raise HTTPException(status_code=404) from None
    except Conflict as exc:
        return _user_row_response(request, uid, error=exc.message, status_code=409)
    context = {"code": code, "target": target, "ttl_hours": state.settings.reset_ttl_hours}
    if is_htmx(request):
        return render(request, "admin/_reset_created.html", context)
    with transaction(request) as conn:
        context["users"] = list_users(conn)
    return render(request, "admin/users.html", context)
