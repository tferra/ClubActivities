"""Borrado de usuarios con pasos registrados y reanudables (FR-028, FR-028a, research R16).

Cada feature que guarde datos de usuario registra su paso con `register_deletion_step`.
Los pasos deben ser idempotentes: si uno falla, el usuario queda en `pending_deletion` y el
borrado se puede reintentar.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Connection, Engine, delete, select, update

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.users import (
    MSG_CURRENT_PASSWORD_WRONG,
    Conflict,
    UserRow,
    ValidationFailed,
    ensure_not_last_admin,
    expire_pending_resets,
    lock_user,
    normalize_email,
)
from garmin_hub.config import Settings
from garmin_hub.db.schema import app_user, audit_event, invitation, password_reset_code
from garmin_hub.keys import DerivedKeys
from garmin_hub.security import passwords
from garmin_hub.security.ip import ip_prefix as to_prefix
from garmin_hub.security.ratelimit import Kind, check_attempts, record_attempt
from garmin_hub.security.sessions import delete_user_sessions

logger = logging.getLogger("garmin_hub.deletion")

CONFIRMATION_WORD = "ELIMINAR"
MSG_CONFIRMATION = f"Escribe {CONFIRMATION_WORD} para confirmar."
MSG_CONFIRM_EMAIL = "El correo no coincide con el del usuario."
MSG_ADMIN_DELETE_ONLY = "Solo se pueden borrar usuarios normales que estén desactivados."
MSG_NOT_PENDING_DELETION = "El usuario no tiene un borrado pendiente."

type By = Literal["self", "admin"]


@dataclass(frozen=True)
class DeletionContext:
    engine: Engine
    now: datetime
    # Las features de ficheros crudos añadirán aquí `raw_store`.


type DeletionStep = Callable[[DeletionContext, UUID], None]


@dataclass(frozen=True)
class RegisteredStep:
    name: str
    order: int
    fn: DeletionStep


class StepFailed(Exception):
    def __init__(self, step: str) -> None:
        self.step = step
        super().__init__(step)


_STEPS: dict[str, RegisteredStep] = {}


def register_deletion_step(name: str, order: int, fn: DeletionStep) -> None:
    if name in _STEPS:
        raise ValueError(f"paso de borrado duplicado: {name}")
    _STEPS[name] = RegisteredStep(name, order, fn)


def registered_steps() -> list[RegisteredStep]:
    return sorted(_STEPS.values(), key=lambda s: (s.order, s.name))


def run_steps(ctx: DeletionContext, user_id: UUID) -> list[str]:
    """Ejecuta los pasos en orden; lanza `StepFailed` con el primero que falle."""
    done = []
    for step in registered_steps():
        try:
            step.fn(ctx, user_id)
        except Exception as exc:
            raise StepFailed(step.name) from exc
        done.append(step.name)
    return done


# --- Pasos propios de la feature 001 ------------------------------------------------------


def delete_reset_codes(ctx: DeletionContext, user_id: UUID) -> None:
    with ctx.engine.begin() as conn:
        conn.execute(delete(password_reset_code).where(password_reset_code.c.user_id == user_id))


def null_invitation_refs(ctx: DeletionContext, user_id: UUID) -> None:
    with ctx.engine.begin() as conn:
        for column in ("created_by_user_id", "used_by_user_id", "revoked_by_user_id"):
            conn.execute(
                update(invitation).where(invitation.c[column] == user_id).values({column: None})
            )


register_deletion_step("delete_reset_codes", 100, delete_reset_codes)
register_deletion_step("null_invitation_refs", 110, null_invitation_refs)


# --- Flujo --------------------------------------------------------------------------------


def _mark_pending(
    conn: Connection,
    target: UserRow,
    *,
    actor_id: UUID,
    by: By,
    ip_prefix: str | None,
    now: datetime,
) -> None:
    """Fase 1: `pending_deletion`, sin sesiones ni códigos pendientes (R16)."""
    conn.execute(
        update(app_user)
        .where(app_user.c.user_id == target.user_id)
        .values(status="pending_deletion", updated_at=now)
    )
    delete_user_sessions(conn, target.user_id)
    expire_pending_resets(conn, target.user_id)
    record_event(
        conn,
        "user.deletion_requested",
        actor_user_id=actor_id,
        subject_user_id=target.user_id,
        ip_prefix=ip_prefix,
        details={"by": by},
        now=now,
    )


def request_self_deletion(
    conn: Connection,
    *,
    user_id: UUID,
    current_password: str,
    confirmation: str,
    ip: str,
    keys: DerivedKeys,
    settings: Settings,
    now: datetime,
) -> str | None:
    """Comprueba contraseña y confirmación y pasa a `pending_deletion`.

    Devuelve un mensaje de error (sin borrar nada) o `None`. Un fallo de contraseña cuenta
    para el límite del par correo + origen, igual que al cambiarla.
    """
    target = lock_user(conn, user_id)
    row = conn.execute(select(app_user.c.password_hash).where(app_user.c.user_id == user_id)).one()
    decision = check_attempts(
        conn,
        email=target.email,
        ip=ip,
        kind=Kind.CURRENT_PASSWORD,
        keys=keys,
        settings=settings,
        now=now,
    )
    if decision.allowed:
        ok = passwords.verify_password(row.password_hash, current_password)
    else:
        passwords.verify_dummy(current_password)
        ok = False
    if not ok:
        record_attempt(
            conn,
            email=target.email,
            ip=ip,
            kind=Kind.CURRENT_PASSWORD,
            succeeded=False,
            keys=keys,
            now=now,
        )
        return MSG_CURRENT_PASSWORD_WRONG
    if confirmation.strip() != CONFIRMATION_WORD:
        return MSG_CONFIRMATION
    ensure_not_last_admin(conn, target)
    _mark_pending(conn, target, actor_id=user_id, by="self", ip_prefix=to_prefix(ip), now=now)
    return None


def request_admin_deletion(
    conn: Connection,
    *,
    admin_id: UUID,
    user_id: UUID,
    confirmation_email: str,
    ip_prefix: str | None,
    now: datetime,
) -> None:
    """Borrado por el administrador: solo usuarios normales desactivados (FR-028a)."""
    target = check_admin_deletable(conn, user_id)
    if normalize_email(confirmation_email) != target.email:
        raise ValidationFailed(MSG_CONFIRM_EMAIL)
    _mark_pending(conn, target, actor_id=admin_id, by="admin", ip_prefix=ip_prefix, now=now)


def check_admin_deletable(conn: Connection, user_id: UUID) -> UserRow:
    target = lock_user(conn, user_id)
    if target.role != "user" or target.status != "deactivated":
        raise Conflict(MSG_ADMIN_DELETE_ONLY)
    return target


def _requested_by(conn: Connection, user_id: UUID) -> tuple[By, UUID | None]:
    row = conn.execute(
        select(audit_event.c.details, audit_event.c.actor_user_id)
        .where(
            audit_event.c.subject_user_id == user_id,
            audit_event.c.event_type == "user.deletion_requested",
        )
        .order_by(audit_event.c.audit_id.desc())
        .limit(1)
    ).first()
    if row is None:
        return "self", user_id
    by: By = json.loads(row.details).get("by", "self")
    return by, row.actor_user_id


def execute_deletion(ctx: DeletionContext, user_id: UUID, *, ip_prefix: str | None) -> list[str]:
    """Fases 2 y 3: pasos registrados y borrado de la fila (`StepFailed` si algo falla)."""
    with ctx.engine.begin() as conn:
        by, actor = _requested_by(conn, user_id)
    try:
        steps = run_steps(ctx, user_id)
    except StepFailed as exc:
        logger.exception("deletion step failed", extra={"step": exc.step})
        with ctx.engine.begin() as conn:
            record_event(
                conn,
                "user.deletion_step_failed",
                actor_user_id=None,
                subject_user_id=user_id,
                ip_prefix=None,
                details={"step": exc.step},
                now=ctx.now,
            )
        raise
    with ctx.engine.begin() as conn:
        delete_user_sessions(conn, user_id)
        conn.execute(delete(app_user).where(app_user.c.user_id == user_id))
        record_event(
            conn,
            "user.deleted",
            actor_user_id=actor,
            subject_user_id=user_id,
            ip_prefix=ip_prefix,
            details={"by": by, "steps": steps},
            now=ctx.now,
        )
    return steps


def check_retryable(conn: Connection, user_id: UUID) -> None:
    target = lock_user(conn, user_id)
    if target.status != "pending_deletion":
        raise Conflict(MSG_NOT_PENDING_DELETION)
