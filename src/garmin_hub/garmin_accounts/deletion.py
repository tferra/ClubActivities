"""Desvinculación y borrado reanudable de cuentas Garmin (FR-020 a FR-022, FR-029, research R14).

Cada feature que guarde datos de una cuenta registra su paso con
`register_account_deletion_step` (orden < 1000). Los pasos deben ser idempotentes: si uno falla,
la cuenta queda en `deleting` y el borrado se puede reintentar. El último paso borra la fila.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, delete, select, update

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.deletion import DeletionContext, register_deletion_step
from garmin_hub.db.schema import (
    data_notice_acceptance,
    garmin_account,
    garmin_login_failure,
    garmin_token,
)
from garmin_hub.garmin_accounts import lease
from garmin_hub.garmin_accounts.accounts import (
    AccountRow,
    GarminActionFailed,
    GarminContext,
    delete_token,
    get_own_account,
)
from garmin_hub.garmin_accounts.errors import (
    MSG_BUSY,
    MSG_CONFIRMATION,
    MSG_MODE_REQUIRED,
    MSG_STATE_NOT_ALLOWED,
)

logger = logging.getLogger("garmin_hub.garmin_accounts.deletion")

ROW_STEP_ORDER = 1000

type Mode = Literal["keep", "delete"]

_c = garmin_account.c


@dataclass(frozen=True)
class AccountDeletionContext:
    engine: Engine
    now: datetime
    # Las features de ficheros crudos añadirán aquí `raw_store`.


type AccountDeletionStep = Callable[[AccountDeletionContext, UUID], None]


@dataclass(frozen=True)
class RegisteredAccountStep:
    name: str
    order: int
    fn: AccountDeletionStep


class AccountStepFailed(Exception):
    def __init__(self, step: str) -> None:
        self.step = step
        super().__init__(step)


_STEPS: dict[str, RegisteredAccountStep] = {}


def register_account_deletion_step(name: str, order: int, fn: AccountDeletionStep) -> None:
    if name in _STEPS:
        raise ValueError(f"paso de borrado de cuenta duplicado: {name}")
    _STEPS[name] = RegisteredAccountStep(name, order, fn)


def registered_account_steps() -> list[RegisteredAccountStep]:
    return sorted(_STEPS.values(), key=lambda s: (s.order, s.name))


# --- Pasos propios de la feature 002 ------------------------------------------------------


def _delete_token(ctx: AccountDeletionContext, account_id: UUID) -> None:
    with ctx.engine.begin() as conn:
        delete_token(conn, account_id)


def _delete_account_row(ctx: AccountDeletionContext, account_id: UUID) -> None:
    with ctx.engine.begin() as conn:
        conn.execute(delete(garmin_account).where(_c.garmin_account_id == account_id))


register_account_deletion_step("garmin_token", 10, _delete_token)
register_account_deletion_step("garmin_account_row", ROW_STEP_ORDER, _delete_account_row)


def run_account_deletion(
    ctx: AccountDeletionContext,
    account_id: UUID,
    *,
    user_id: UUID,
    actor_id: UUID | None,
    ip_prefix: str | None,
) -> list[str]:
    """Ejecuta los pasos en orden; `AccountStepFailed` con el primero que falle."""
    done = []
    for step in registered_account_steps():
        try:
            step.fn(ctx, account_id)
        except Exception:
            logger.exception(
                "account deletion step failed",
                extra={"step": step.name, "garmin_account_id": str(account_id)},
            )
            with ctx.engine.begin() as conn:
                record_event(
                    conn,
                    "garmin.account_deletion_step_failed",
                    actor_user_id=None,
                    subject_user_id=user_id,
                    ip_prefix=None,
                    details={"garmin_account_id": str(account_id), "step": step.name},
                    now=ctx.now,
                )
            raise AccountStepFailed(step.name) from None
        done.append(step.name)
    with ctx.engine.begin() as conn:
        record_event(
            conn,
            "garmin.account_deleted",
            actor_user_id=actor_id,
            subject_user_id=user_id,
            ip_prefix=ip_prefix,
            details={"garmin_account_id": str(account_id), "steps": done},
            now=ctx.now,
        )
    return done


# --- Flujos del usuario (US5) -------------------------------------------------------------


def _confirmed(account: AccountRow, confirmation: str) -> bool:
    return confirmation.strip().casefold() == account.alias.casefold()


def _audit(
    ctx: GarminContext,
    event_type: str,
    account: AccountRow,
    ip_prefix: str | None,
    now: datetime,
    **details: str,
) -> None:
    with ctx.engine.begin() as conn:
        record_event(
            conn,
            event_type,
            actor_user_id=account.user_id,
            subject_user_id=account.user_id,
            ip_prefix=ip_prefix,
            details={"garmin_account_id": str(account.garmin_account_id), **details},
            now=now,
        )


def unlink(
    ctx: GarminContext,
    *,
    user_id: UUID,
    account_id: UUID,
    mode: str,
    confirmation: str,
    now: datetime,
    ip_prefix: str | None,
) -> Mode:
    """Desvincula conservando (`keep`) o borrando (`delete`) los datos.

    Reclama el candado de la cuenta (R6), así que no compite con una comprobación ni con una
    reautenticación en curso. Con `delete`, lanza `AccountStepFailed` si un paso falla.
    """
    if mode not in ("keep", "delete"):
        raise GarminActionFailed(MSG_MODE_REQUIRED)
    with ctx.engine.begin() as conn:
        account = get_own_account(conn, user_id, account_id)
        if account is None or not account.is_active:
            raise GarminActionFailed(MSG_STATE_NOT_ALLOWED, "conflict")
        if not _confirmed(account, confirmation):
            raise GarminActionFailed(MSG_CONFIRMATION)
        if not lease.acquire(conn, account_id, now, ctx.settings.garmin_request_lease_seconds):
            raise GarminActionFailed(MSG_BUSY, "conflict")
        delete_token(conn, account_id)
        values = (
            {"status": "unlinked", "unlinked_at": now}
            if mode == "keep"
            else {"status": "deleting", "deletion_requested_at": now}
        )
        conn.execute(
            update(garmin_account)
            .where(_c.garmin_account_id == account_id)
            .values(**values, error_code=None, request_lease_until=None, updated_at=now)
        )
        record_event(
            conn,
            "garmin.account_unlinked",
            actor_user_id=user_id,
            subject_user_id=user_id,
            ip_prefix=ip_prefix,
            details={
                "garmin_account_id": str(account_id),
                "data": "kept" if mode == "keep" else "deleted",
            },
            now=now,
        )
    ctx.registry.discard_for_account(account_id)
    if mode == "delete":
        run_account_deletion(
            AccountDeletionContext(ctx.engine, now),
            account_id,
            user_id=user_id,
            actor_id=user_id,
            ip_prefix=ip_prefix,
        )
        return "delete"
    return "keep"


def request_data_deletion(
    ctx: GarminContext,
    *,
    user_id: UUID,
    account_id: UUID,
    confirmation: str,
    now: datetime,
    ip_prefix: str | None,
) -> None:
    """Borra los datos de una cuenta ya desvinculada (`unlinked` → `deleting`, US5-5)."""
    with ctx.engine.begin() as conn:
        account = get_own_account(conn, user_id, account_id)
        if account is None or account.status != "unlinked":
            raise GarminActionFailed(MSG_STATE_NOT_ALLOWED, "conflict")
        if not _confirmed(account, confirmation):
            raise GarminActionFailed(MSG_CONFIRMATION)
        if not lease.acquire(conn, account_id, now, ctx.settings.garmin_request_lease_seconds):
            raise GarminActionFailed(MSG_BUSY, "conflict")
        conn.execute(
            update(garmin_account)
            .where(_c.garmin_account_id == account_id)
            .values(
                status="deleting",
                deletion_requested_at=now,
                request_lease_until=None,
                updated_at=now,
            )
        )
    _audit(ctx, "garmin.data_deletion_requested", account, ip_prefix, now)
    run_account_deletion(
        AccountDeletionContext(ctx.engine, now),
        account_id,
        user_id=user_id,
        actor_id=user_id,
        ip_prefix=ip_prefix,
    )


def retry_deletion(
    ctx: GarminContext, *, user_id: UUID, account_id: UUID, now: datetime, ip_prefix: str | None
) -> None:
    with ctx.engine.connect() as conn:
        account = get_own_account(conn, user_id, account_id)
    if account is None or account.status != "deleting":
        raise GarminActionFailed(MSG_STATE_NOT_ALLOWED, "conflict")
    run_account_deletion(
        AccountDeletionContext(ctx.engine, now),
        account_id,
        user_id=user_id,
        actor_id=user_id,
        ip_prefix=ip_prefix,
    )


# --- Borrado del usuario (registro de la feature 001, FR-029) -----------------------------


def delete_user_garmin_data(ctx: DeletionContext, user_id: UUID) -> None:
    """Borra todas las cuentas Garmin del usuario y sus filas técnicas. Es idempotente."""
    with ctx.engine.begin() as conn:
        account_ids = list(
            conn.execute(select(_c.garmin_account_id).where(_c.user_id == user_id)).scalars()
        )
        conn.execute(
            update(garmin_account)
            .where(_c.user_id == user_id, _c.status != "deleting")
            .values(
                status="deleting",
                error_code=None,
                deletion_requested_at=ctx.now,
                request_lease_until=None,
                updated_at=ctx.now,
            )
        )
        conn.execute(delete(garmin_token).where(garmin_token.c.garmin_account_id.in_(account_ids)))
    account_ctx = AccountDeletionContext(ctx.engine, ctx.now)
    for account_id in account_ids:
        run_account_deletion(
            account_ctx, account_id, user_id=user_id, actor_id=None, ip_prefix=None
        )
    with ctx.engine.begin() as conn:
        conn.execute(
            delete(data_notice_acceptance).where(data_notice_acceptance.c.user_id == user_id)
        )
        conn.execute(delete(garmin_login_failure).where(garmin_login_failure.c.user_id == user_id))


register_deletion_step("garmin_accounts", 50, delete_user_garmin_data)
