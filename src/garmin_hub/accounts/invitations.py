"""Invitaciones de un solo uso ligadas a un correo (FR-005 a FR-014, research R17)."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Row, insert, select, update
from sqlalchemy.exc import IntegrityError

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.users import (
    MSG_EMAIL_TAKEN,
    Conflict,
    NotFound,
    ValidationFailed,
    email_exists,
    insert_user,
    normalize_email,
    validate_display_name,
    validate_email,
)
from garmin_hub.config import Settings
from garmin_hub.db.schema import app_user, invitation
from garmin_hub.keys import DerivedKeys
from garmin_hub.security import passwords
from garmin_hub.security.codes import code_hash, generate_code

MSG_EMAIL_PENDING = "Ese correo ya tiene una invitación pendiente; revócala para generar otra."
MSG_TTL = "La caducidad debe estar entre 1 y 30 días."
MSG_NOTE = "La nota no puede tener más de 200 caracteres."
MIN_TTL_DAYS, MAX_TTL_DAYS = 1, 30

STATUS_LABELS = {
    "pending": "Pendiente",
    "used": "Usada",
    "expired": "Caducada",
    "revoked": "Revocada",
}


def create_invitation(
    conn: Connection,
    *,
    admin_id: UUID,
    email: str,
    note: str | None,
    ttl_days: int | None,
    ip_prefix: str | None,
    keys: DerivedKeys,
    settings: Settings,
    now: datetime,
) -> tuple[UUID, str]:
    """Crea una invitación y devuelve su id y el código en claro (se muestra una sola vez)."""
    error = validate_email(email)
    if error:
        raise ValidationFailed(error)
    email = normalize_email(email)
    note = (note or "").strip() or None
    if note is not None and len(note) > 200:
        raise ValidationFailed(MSG_NOTE)
    if ttl_days is None:
        ttl_days = settings.invite_ttl_days
    if not MIN_TTL_DAYS <= ttl_days <= MAX_TTL_DAYS:
        raise ValidationFailed(MSG_TTL)
    if email_exists(conn, email):
        raise ValidationFailed(MSG_EMAIL_TAKEN)

    conn.execute(
        update(invitation)
        .where(
            invitation.c.email == email,
            invitation.c.status == "pending",
            invitation.c.expires_at <= now,
        )
        .values(status="expired")
    )
    invitation_id = uuid.uuid4()
    code = generate_code()
    try:
        with conn.begin_nested():
            conn.execute(
                insert(invitation).values(
                    invitation_id=invitation_id,
                    code_hash=code_hash(keys, code),
                    email=email,
                    note=note,
                    status="pending",
                    created_at=now,
                    expires_at=now + timedelta(days=ttl_days),
                    created_by_user_id=admin_id,
                )
            )
    except IntegrityError:
        raise ValidationFailed(MSG_EMAIL_PENDING) from None
    record_event(
        conn,
        "invitation.created",
        actor_user_id=admin_id,
        subject_user_id=None,
        ip_prefix=ip_prefix,
        details={"invitation_id": str(invitation_id), "ttl_days": ttl_days},
        now=now,
    )
    return invitation_id, code


@dataclass(frozen=True)
class InvitationRow:
    invitation_id: UUID
    email: str
    note: str | None
    status: str
    status_label: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    used_by_name: str | None

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"


def effective_status(status: str, expires_at: datetime, now: datetime) -> str:
    if status == "pending" and expires_at <= now:
        return "expired"
    return status


def list_invitations(conn: Connection, now: datetime) -> list[InvitationRow]:
    used_by = app_user.alias("used_by")
    stmt = (
        select(invitation, used_by.c.display_name.label("used_by_name"))
        .select_from(
            invitation.outerjoin(used_by, used_by.c.user_id == invitation.c.used_by_user_id)
        )
        .order_by(invitation.c.created_at.desc())
    )
    return [_to_row(r, now) for r in conn.execute(stmt)]


def get_invitation_row(conn: Connection, invitation_id: UUID, now: datetime) -> InvitationRow:
    used_by = app_user.alias("used_by")
    stmt = (
        select(invitation, used_by.c.display_name.label("used_by_name"))
        .select_from(
            invitation.outerjoin(used_by, used_by.c.user_id == invitation.c.used_by_user_id)
        )
        .where(invitation.c.invitation_id == invitation_id)
    )
    row = conn.execute(stmt).first()
    if row is None:
        raise NotFound
    return _to_row(row, now)


def _to_row(r: Row[Any], now: datetime) -> InvitationRow:
    status = effective_status(r.status, r.expires_at, now)
    return InvitationRow(
        invitation_id=r.invitation_id,
        email=r.email,
        note=r.note,
        status=status,
        status_label=STATUS_LABELS[status],
        created_at=r.created_at,
        expires_at=r.expires_at,
        used_at=r.used_at,
        used_by_name=r.used_by_name,
    )


class InvalidCode(Exception):
    """Código usado, caducado, revocado, inexistente o no utilizable (mensaje genérico)."""


MSG_INVALID_CODE = "El código no es válido o ha caducado."


@dataclass(frozen=True)
class PendingInvitation:
    invitation_id: UUID
    email: str


def peek_invitation(
    conn: Connection, code: str, keys: DerivedKeys, now: datetime
) -> PendingInvitation | None:
    """Devuelve la invitación pendiente y no caducada de ese código, sin consumirla."""
    row = conn.execute(
        select(invitation.c.invitation_id, invitation.c.email).where(
            invitation.c.code_hash == code_hash(keys, code),
            invitation.c.status == "pending",
            invitation.c.expires_at > now,
        )
    ).first()
    return PendingInvitation(row.invitation_id, row.email) if row else None


def redeem_invitation(
    conn: Connection,
    *,
    code: str,
    display_name: str,
    password: str,
    keys: DerivedKeys,
    ip_prefix: str | None,
    now: datetime,
) -> UUID:
    """Consume el código y crea el usuario en la misma transacción (FR-009, FR-011, FR-014).

    Si la validación falla no se consume el código. Si el correo ya existe (registrado por
    otra vía), lanza `InvalidCode`; la transacción del llamador se revierte.
    """
    pending = peek_invitation(conn, code, keys, now)
    if pending is None:
        raise InvalidCode
    error = validate_display_name(display_name) or passwords.validate_password(
        password, email=pending.email, display_name=display_name
    )
    if error:
        raise ValidationFailed(error)
    claimed = conn.execute(
        update(invitation)
        .where(
            invitation.c.code_hash == code_hash(keys, code),
            invitation.c.status == "pending",
            invitation.c.expires_at > now,
        )
        .values(status="used", used_at=now)
    )
    if claimed.rowcount != 1:
        raise InvalidCode
    try:
        with conn.begin_nested():
            user_id = insert_user(
                conn,
                email=pending.email,
                display_name=display_name,
                password=password,
                role="user",
                now=now,
            )
    except IntegrityError:
        raise InvalidCode from None
    conn.execute(
        update(invitation)
        .where(invitation.c.invitation_id == pending.invitation_id)
        .values(used_by_user_id=user_id)
    )
    record_event(
        conn,
        "user.signed_up",
        actor_user_id=user_id,
        subject_user_id=user_id,
        ip_prefix=ip_prefix,
        details={"invitation_id": str(pending.invitation_id)},
        now=now,
    )
    return user_id


MSG_NOT_PENDING = "La invitación ya no está pendiente."


def revoke_invitation(
    conn: Connection,
    *,
    admin_id: UUID,
    invitation_id: UUID,
    ip_prefix: str | None,
    now: datetime,
) -> InvitationRow:
    """Revoca una invitación pendiente y no caducada (FR-010)."""
    current = get_invitation_row(conn, invitation_id, now)
    if current.status != "pending":
        raise Conflict(MSG_NOT_PENDING)
    result = conn.execute(
        update(invitation)
        .where(invitation.c.invitation_id == invitation_id, invitation.c.status == "pending")
        .values(status="revoked", revoked_at=now, revoked_by_user_id=admin_id)
    )
    if result.rowcount != 1:
        raise Conflict(MSG_NOT_PENDING)
    record_event(
        conn,
        "invitation.revoked",
        actor_user_id=admin_id,
        subject_user_id=None,
        ip_prefix=ip_prefix,
        details={"invitation_id": str(invitation_id)},
        now=now,
    )
    return get_invitation_row(conn, invitation_id, now)
