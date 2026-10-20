"""Tablas de la feature 001 (data-model.md) con SQLAlchemy Core.

Las tablas se definen sin schema; el engine traduce `None` al schema configurado
(`schema_translate_map`), así el mismo código sirve para `gh` y para los schemas de test.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    BINARY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Dialect,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    TypeDecorator,
    Unicode,
    Uuid,
)
from sqlalchemy.dialects.mssql import DATETIME2
from sqlalchemy.types import TypeEngine


class UtcDateTime(TypeDecorator[datetime]):
    """`DATETIME2(3)` en UTC: se guarda sin zona y se lee con `tzinfo=UTC`."""

    impl = DATETIME2(3)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[datetime]:
        if dialect.name == "mssql":
            return dialect.type_descriptor(DATETIME2(3))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("se esperaba un datetime con zona horaria")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


# BIGINT IDENTITY en SQL Server; INTEGER en SQLite (solo comprobación local, ver tests).
BigIdentity = BigInteger().with_variant(Integer(), "sqlite")

metadata = MetaData()

app_user = Table(
    "app_user",
    metadata,
    Column("user_id", Uuid, primary_key=True),
    Column("email", Unicode(254), nullable=False),
    Column("display_name", Unicode(100), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(16), nullable=False),
    Column("status", String(20), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Column("password_changed_at", UtcDateTime, nullable=False),
    Column("last_login_at", UtcDateTime, nullable=True),
    CheckConstraint("role IN ('user', 'admin')", name="CK_app_user_role"),
    CheckConstraint(
        "status IN ('active', 'deactivated', 'pending_deletion')", name="CK_app_user_status"
    ),
    Index("UX_app_user_email", "email", unique=True),
)

invitation = Table(
    "invitation",
    metadata,
    Column("invitation_id", Uuid, primary_key=True),
    Column("code_hash", BINARY(32), nullable=False, unique=True),
    Column("email", Unicode(254), nullable=False),
    Column("note", Unicode(200), nullable=True),
    Column("status", String(16), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("expires_at", UtcDateTime, nullable=False),
    Column("created_by_user_id", Uuid, ForeignKey("app_user.user_id"), nullable=True),
    Column("used_at", UtcDateTime, nullable=True),
    Column("used_by_user_id", Uuid, ForeignKey("app_user.user_id"), nullable=True),
    Column("revoked_at", UtcDateTime, nullable=True),
    Column("revoked_by_user_id", Uuid, ForeignKey("app_user.user_id"), nullable=True),
    CheckConstraint(
        "status IN ('pending', 'used', 'revoked', 'expired')", name="CK_invitation_status"
    ),
    CheckConstraint("expires_at > created_at", name="CK_invitation_expires"),
)
Index(
    "UX_invitation_pending_email",
    invitation.c.email,
    unique=True,
    mssql_where=invitation.c.status == "pending",
    sqlite_where=invitation.c.status == "pending",
)
Index("IX_invitation_created_at", invitation.c.created_at.desc())

password_reset_code = Table(
    "password_reset_code",
    metadata,
    Column("reset_id", Uuid, primary_key=True),
    Column("user_id", Uuid, ForeignKey("app_user.user_id"), nullable=False),
    Column("code_hash", BINARY(32), nullable=False, unique=True),
    Column("status", String(16), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("expires_at", UtcDateTime, nullable=False),
    Column("created_by_user_id", Uuid, nullable=True),
    Column("used_at", UtcDateTime, nullable=True),
    CheckConstraint(
        "status IN ('pending', 'used', 'superseded', 'expired')", name="CK_reset_status"
    ),
)
Index(
    "UX_reset_pending_user",
    password_reset_code.c.user_id,
    unique=True,
    mssql_where=password_reset_code.c.status == "pending",
    sqlite_where=password_reset_code.c.status == "pending",
)

user_session = Table(
    "user_session",
    metadata,
    Column("session_hash", BINARY(32), primary_key=True),
    Column("user_id", Uuid, ForeignKey("app_user.user_id"), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("last_seen_at", UtcDateTime, nullable=False),
    Column("expires_at", UtcDateTime, nullable=False),
    Index("IX_user_session_user", "user_id"),
    Index("IX_user_session_expires", "expires_at"),
)

login_attempt = Table(
    "login_attempt",
    metadata,
    Column("attempt_id", BigIdentity, Identity(), primary_key=True),
    Column("attempted_at", UtcDateTime, nullable=False),
    Column("email_hmac", BINARY(32), nullable=True),
    Column("ip_hmac", BINARY(32), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("succeeded", Boolean, nullable=False),
    CheckConstraint(
        "kind IN ('login', 'code_redeem', 'current_password')", name="CK_login_attempt_kind"
    ),
    Index("IX_login_attempt_email", "email_hmac", "attempted_at"),
    Index("IX_login_attempt_ip", "ip_hmac", "attempted_at"),
)

audit_event = Table(
    "audit_event",
    metadata,
    Column("audit_id", BigIdentity, Identity(), primary_key=True),
    Column("occurred_at", UtcDateTime, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("actor_user_id", Uuid, nullable=True),
    Column("subject_user_id", Uuid, nullable=True),
    Column("ip_prefix", String(50), nullable=True),
    Column("details", Unicode(1000), nullable=True),
)
Index("IX_audit_event_occurred", audit_event.c.occurred_at.desc())
Index("IX_audit_event_subject", audit_event.c.subject_user_id, audit_event.c.occurred_at)
