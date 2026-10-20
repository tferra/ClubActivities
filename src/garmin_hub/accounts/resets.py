"""Códigos de restablecimiento generados por el administrador (FR-029, US8)."""

import uuid
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, exists, insert, select, update

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.invitations import InvalidCode
from garmin_hub.accounts.users import (
    Conflict,
    ValidationFailed,
    lock_user,
    normalize_email,
)
from garmin_hub.config import Settings
from garmin_hub.db.schema import app_user, password_reset_code
from garmin_hub.keys import DerivedKeys
from garmin_hub.security import passwords
from garmin_hub.security.codes import code_hash, generate_code
from garmin_hub.security.sessions import delete_user_sessions

MSG_RESET_NOT_ACTIVE = "Solo se pueden generar códigos para usuarios activos."


def create_reset_code(
    conn: Connection,
    *,
    admin_id: UUID,
    user_id: UUID,
    keys: DerivedKeys,
    settings: Settings,
    ip_prefix: str | None,
    now: datetime,
) -> str:
    """Genera un código de un solo uso; anula el pendiente anterior en la misma transacción."""
    target = lock_user(conn, user_id)
    if target.status != "active":
        raise Conflict(MSG_RESET_NOT_ACTIVE)
    conn.execute(
        update(password_reset_code)
        .where(
            password_reset_code.c.user_id == user_id,
            password_reset_code.c.status == "pending",
        )
        .values(status="superseded")
    )
    reset_id = uuid.uuid4()
    code = generate_code()
    conn.execute(
        insert(password_reset_code).values(
            reset_id=reset_id,
            user_id=user_id,
            code_hash=code_hash(keys, code),
            status="pending",
            created_at=now,
            expires_at=now + timedelta(hours=settings.reset_ttl_hours),
            created_by_user_id=admin_id,
        )
    )
    record_event(
        conn,
        "reset.created",
        actor_user_id=admin_id,
        subject_user_id=user_id,
        ip_prefix=ip_prefix,
        details={"reset_id": str(reset_id)},
        now=now,
    )
    return code


def redeem_reset_code(
    conn: Connection,
    *,
    email: str,
    code: str,
    new_password: str,
    keys: DerivedKeys,
    ip_prefix: str | None,
    now: datetime,
) -> UUID:
    """Fija una contraseña nueva y cierra todas las sesiones (FR-029).

    El código solo vale si es del usuario de ese correo, está pendiente, no ha caducado y el
    usuario está activo. Si la contraseña no cumple la política, el código no se consume.
    """
    hashed = code_hash(keys, code)
    row = conn.execute(
        select(
            password_reset_code.c.reset_id,
            app_user.c.user_id,
            app_user.c.email,
            app_user.c.display_name,
        )
        .join(app_user, app_user.c.user_id == password_reset_code.c.user_id)
        .where(
            password_reset_code.c.code_hash == hashed,
            password_reset_code.c.status == "pending",
            password_reset_code.c.expires_at > now,
            app_user.c.email == normalize_email(email),
            app_user.c.status == "active",
        )
    ).first()
    if row is None:
        raise InvalidCode
    error = passwords.validate_password(
        new_password, email=row.email, display_name=row.display_name
    )
    if error:
        raise ValidationFailed(error)
    active_user = exists().where(
        app_user.c.user_id == password_reset_code.c.user_id, app_user.c.status == "active"
    )
    claimed = conn.execute(
        update(password_reset_code)
        .where(
            password_reset_code.c.reset_id == row.reset_id,
            password_reset_code.c.status == "pending",
            password_reset_code.c.expires_at > now,
            active_user,
        )
        .values(status="used", used_at=now)
    )
    if claimed.rowcount != 1:
        raise InvalidCode
    conn.execute(
        update(app_user)
        .where(app_user.c.user_id == row.user_id)
        .values(
            password_hash=passwords.hash_password(new_password),
            password_changed_at=now,
            updated_at=now,
        )
    )
    closed = delete_user_sessions(conn, row.user_id)
    record_event(
        conn,
        "reset.used",
        actor_user_id=row.user_id,
        subject_user_id=row.user_id,
        ip_prefix=ip_prefix,
        details={"reset_id": str(row.reset_id), "sessions_closed": closed},
        now=now,
    )
    return row.user_id
