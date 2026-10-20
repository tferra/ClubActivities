"""Usuarios: alta de administradores, autenticación, perfil y administración."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, func, insert, select, update

from garmin_hub.accounts.audit import record_event
from garmin_hub.config import Settings
from garmin_hub.db.schema import app_user, invitation, password_reset_code
from garmin_hub.keys import DerivedKeys
from garmin_hub.security import passwords
from garmin_hub.security.ip import ip_prefix
from garmin_hub.security.ratelimit import Decision, Kind, check_attempts, record_attempt
from garmin_hub.security.sessions import delete_user_sessions

MSG_EMAIL_INVALID = "El correo no tiene un formato válido."
MSG_EMAIL_TAKEN = "Ya existe un usuario con ese correo."
MSG_EMAIL_INVITED = "Ese correo tiene una invitación pendiente; revócala antes de continuar."
MSG_NAME_INVALID = "El nombre debe tener entre 1 y 100 caracteres."

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationFailed(Exception):
    """Error de validación con un mensaje en español para el usuario."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class Conflict(Exception):
    """La operación no es posible en el estado actual (HTTP 409)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFound(Exception):
    """El recurso no existe (HTTP 404)."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str | None:
    email = normalize_email(email)
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return MSG_EMAIL_INVALID
    return None


def validate_display_name(name: str) -> str | None:
    if not 1 <= len(name.strip()) <= 100:
        return MSG_NAME_INVALID
    return None


def email_exists(conn: Connection, email: str) -> bool:
    stmt = select(app_user.c.user_id).where(app_user.c.email == normalize_email(email))
    return conn.execute(stmt).first() is not None


def has_pending_invitation(conn: Connection, email: str, now: datetime) -> bool:
    stmt = select(invitation.c.invitation_id).where(
        invitation.c.email == normalize_email(email),
        invitation.c.status == "pending",
        invitation.c.expires_at > now,
    )
    return conn.execute(stmt).first() is not None


def insert_user(
    conn: Connection,
    *,
    email: str,
    display_name: str,
    password: str,
    role: str,
    now: datetime,
) -> UUID:
    user_id = uuid.uuid4()
    conn.execute(
        insert(app_user).values(
            user_id=user_id,
            email=normalize_email(email),
            display_name=display_name.strip(),
            password_hash=passwords.hash_password(password),
            role=role,
            status="active",
            created_at=now,
            updated_at=now,
            password_changed_at=now,
        )
    )
    return user_id


def check_new_admin(conn: Connection, *, email: str, display_name: str, now: datetime) -> None:
    """Validaciones de `admin create` previas a pedir la contraseña."""
    error = validate_email(email) or validate_display_name(display_name)
    if error:
        raise ValidationFailed(error)
    if email_exists(conn, email):
        raise ValidationFailed(MSG_EMAIL_TAKEN)
    if has_pending_invitation(conn, email, now):
        raise ValidationFailed(MSG_EMAIL_INVITED)


def create_admin(
    conn: Connection, *, email: str, display_name: str, password: str, now: datetime
) -> UUID:
    """Crea un administrador (solo desde la CLI, FR-003 y FR-004)."""
    check_new_admin(conn, email=email, display_name=display_name, now=now)
    error = passwords.validate_password(
        password, email=normalize_email(email), display_name=display_name
    )
    if error:
        raise ValidationFailed(error)
    user_id = insert_user(
        conn, email=email, display_name=display_name, password=password, role="admin", now=now
    )
    record_event(
        conn,
        "admin.created",
        actor_user_id=None,
        subject_user_id=user_id,
        ip_prefix=None,
        details={"via": "cli"},
        now=now,
    )
    return user_id


@dataclass(frozen=True)
class UserRow:
    user_id: UUID
    email: str
    display_name: str
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None


MSG_LOGIN_FAILED = "Correo o contraseña incorrectos."


@dataclass(frozen=True)
class AuthFailure:
    reason: str  # bad_credentials | blocked_pair | blocked_ip | inactive


def authenticate(
    conn: Connection,
    *,
    email: str,
    password: str,
    ip: str,
    decision: Decision,
    keys: DerivedKeys,
    settings: Settings,
    now: datetime,
) -> UUID | AuthFailure:
    """Verifica credenciales con una única verificación argon2 por petición (SC-005).

    Un usuario en `pending_deletion` se trata como inexistente.
    """
    email = normalize_email(email)
    row = conn.execute(
        select(app_user.c.user_id, app_user.c.password_hash, app_user.c.status).where(
            app_user.c.email == email, app_user.c.status != "pending_deletion"
        )
    ).first()
    subject = row.user_id if row is not None else None
    ip_pre = ip_prefix(ip)

    if decision.crossed_soft_limit(settings):
        record_event(
            conn,
            "auth.email_soft_limit",
            actor_user_id=None,
            subject_user_id=subject,
            ip_prefix=ip_pre,
            details={"failures_1h": decision.email_failures},
            now=now,
        )

    if not decision.allowed:
        passwords.verify_dummy(password)
        reason = decision.outcome.value
    elif row is None:
        passwords.verify_dummy(password)
        reason = "bad_credentials"
    elif row.status != "active":
        passwords.verify_dummy(password)
        reason = "inactive"
    elif not passwords.verify_password(row.password_hash, password):
        reason = "bad_credentials"
    else:
        reason = ""

    record_attempt(
        conn, email=email, ip=ip, kind=Kind.LOGIN, succeeded=not reason, keys=keys, now=now
    )
    if reason:
        record_event(
            conn,
            "auth.login_failed",
            actor_user_id=None,
            subject_user_id=subject,
            ip_prefix=ip_pre,
            details={"reason": reason},
            now=now,
        )
        return AuthFailure(reason)

    assert row is not None  # noqa: S101
    values: dict[str, object] = {"last_login_at": now}
    if passwords.needs_rehash(row.password_hash):
        values["password_hash"] = passwords.hash_password(password)
    conn.execute(update(app_user).where(app_user.c.user_id == row.user_id).values(**values))
    record_event(
        conn,
        "auth.login_succeeded",
        actor_user_id=row.user_id,
        subject_user_id=row.user_id,
        ip_prefix=ip_pre,
        now=now,
    )
    return row.user_id


MSG_CURRENT_PASSWORD_WRONG = "La contraseña actual no es correcta."  # noqa: S105


def change_display_name(
    conn: Connection, user_id: UUID, name: str, *, ip_prefix: str | None, now: datetime
) -> None:
    error = validate_display_name(name)
    if error:
        raise ValidationFailed(error)
    conn.execute(
        update(app_user)
        .where(app_user.c.user_id == user_id)
        .values(display_name=name.strip(), updated_at=now)
    )
    record_event(
        conn,
        "user.name_changed",
        actor_user_id=user_id,
        subject_user_id=user_id,
        ip_prefix=ip_prefix,
        now=now,
    )


@dataclass(frozen=True)
class PasswordChange:
    error: str | None = None
    sessions_closed: int = 0


def change_password(
    conn: Connection,
    *,
    user_id: UUID,
    current_password: str,
    new_password: str,
    current_session_hash: bytes,
    ip: str,
    keys: DerivedKeys,
    settings: Settings,
    now: datetime,
) -> PasswordChange:
    """Cambia la contraseña (FR-023). Los fallos de la actual cuentan para el par (FR-030).

    Devuelve el error en lugar de lanzarlo para que el intento fallido quede guardado.
    """
    row = conn.execute(
        select(app_user.c.email, app_user.c.display_name, app_user.c.password_hash).where(
            app_user.c.user_id == user_id
        )
    ).one()
    decision = check_attempts(
        conn,
        email=row.email,
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
    ip_pre = ip_prefix(ip)
    if not ok:
        record_attempt(
            conn,
            email=row.email,
            ip=ip,
            kind=Kind.CURRENT_PASSWORD,
            succeeded=False,
            keys=keys,
            now=now,
        )
        record_event(
            conn,
            "user.password_change_failed",
            actor_user_id=user_id,
            subject_user_id=user_id,
            ip_prefix=ip_pre,
            now=now,
        )
        return PasswordChange(error=MSG_CURRENT_PASSWORD_WRONG)
    error = passwords.validate_password(
        new_password, email=row.email, display_name=row.display_name
    )
    if error:
        return PasswordChange(error=error)
    conn.execute(
        update(app_user)
        .where(app_user.c.user_id == user_id)
        .values(
            password_hash=passwords.hash_password(new_password),
            password_changed_at=now,
            updated_at=now,
        )
    )
    closed = delete_user_sessions(conn, user_id, except_hash=current_session_hash)
    record_event(
        conn,
        "user.password_changed",
        actor_user_id=user_id,
        subject_user_id=user_id,
        ip_prefix=ip_pre,
        details={"sessions_closed": closed},
        now=now,
    )
    return PasswordChange(sessions_closed=closed)


def get_user(conn: Connection, user_id: UUID) -> UserRow:
    row = conn.execute(
        select(
            app_user.c.user_id,
            app_user.c.email,
            app_user.c.display_name,
            app_user.c.role,
            app_user.c.status,
            app_user.c.created_at,
            app_user.c.last_login_at,
        ).where(app_user.c.user_id == user_id)
    ).first()
    if row is None:
        raise NotFound
    return UserRow(**row._mapping)


MSG_SELF_DEACTIVATE = "No puedes desactivarte a ti mismo."
MSG_LAST_ADMIN = "No se puede dejar la aplicación sin ningún administrador activo."
MSG_NOT_ACTIVE = "El usuario no está activo."
MSG_NOT_DEACTIVATED = "El usuario no está desactivado."

_USER_COLUMNS = (
    app_user.c.user_id,
    app_user.c.email,
    app_user.c.display_name,
    app_user.c.role,
    app_user.c.status,
    app_user.c.created_at,
    app_user.c.last_login_at,
)


def list_users(conn: Connection) -> list[UserRow]:
    rows = conn.execute(select(*_USER_COLUMNS).order_by(app_user.c.created_at))
    return [UserRow(**r._mapping) for r in rows]


def lock_user(conn: Connection, user_id: UUID) -> UserRow:
    row = conn.execute(
        select(*_USER_COLUMNS)
        .where(app_user.c.user_id == user_id)
        .with_hint(app_user, "WITH (UPDLOCK, HOLDLOCK)", "mssql")
    ).first()
    if row is None:
        raise NotFound
    return UserRow(**row._mapping)


def ensure_not_last_admin(conn: Connection, target: UserRow) -> None:
    """Rechaza dejar 0 administradores activos (FR-027, research R18)."""
    if target.role != "admin" or target.status != "active":
        return
    active_admins = conn.execute(
        select(func.count())
        .select_from(app_user)
        .where(app_user.c.role == "admin", app_user.c.status == "active")
        .with_hint(app_user, "WITH (UPDLOCK, HOLDLOCK)", "mssql")
    ).scalar_one()
    if active_admins <= 1:
        raise Conflict(MSG_LAST_ADMIN)


def expire_pending_resets(conn: Connection, user_id: UUID) -> int:
    """Anula los códigos de restablecimiento pendientes (FR-029)."""
    return (
        conn.execute(
            update(password_reset_code)
            .where(
                password_reset_code.c.user_id == user_id,
                password_reset_code.c.status == "pending",
            )
            .values(status="expired")
        ).rowcount
        or 0
    )


def deactivate_user(
    conn: Connection, *, admin_id: UUID, user_id: UUID, ip_prefix: str | None, now: datetime
) -> UserRow:
    """Desactiva: cierra sesiones, anula códigos y bloquea el acceso (FR-025 a FR-027)."""
    if user_id == admin_id:
        raise Conflict(MSG_SELF_DEACTIVATE)
    target = lock_user(conn, user_id)
    if target.status != "active":
        raise Conflict(MSG_NOT_ACTIVE)
    ensure_not_last_admin(conn, target)
    conn.execute(
        update(app_user)
        .where(app_user.c.user_id == user_id)
        .values(status="deactivated", updated_at=now)
    )
    closed = delete_user_sessions(conn, user_id)
    expired = expire_pending_resets(conn, user_id)
    record_event(
        conn,
        "user.deactivated",
        actor_user_id=admin_id,
        subject_user_id=user_id,
        ip_prefix=ip_prefix,
        details={"sessions_closed": closed, "resets_expired": expired},
        now=now,
    )
    return get_user(conn, user_id)


def reactivate_user(
    conn: Connection, *, admin_id: UUID, user_id: UUID, ip_prefix: str | None, now: datetime
) -> UserRow:
    target = lock_user(conn, user_id)
    if target.status != "deactivated":
        raise Conflict(MSG_NOT_DEACTIVATED)
    conn.execute(
        update(app_user)
        .where(app_user.c.user_id == user_id)
        .values(status="active", updated_at=now)
    )
    record_event(
        conn,
        "user.reactivated",
        actor_user_id=admin_id,
        subject_user_id=user_id,
        ip_prefix=ip_prefix,
        now=now,
    )
    return get_user(conn, user_id)
