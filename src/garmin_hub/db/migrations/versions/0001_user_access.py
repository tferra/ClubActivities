"""user access: app_user, invitation, password_reset_code, user_session, login_attempt, audit_event

Revision ID: 0001_user_access
Revises:
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIME2

revision = "0001_user_access"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    return op.get_context().opts["version_table_schema"]


def _dt(name, nullable=False):
    return sa.Column(name, DATETIME2(3), nullable=nullable)


def upgrade() -> None:
    s = _schema()
    op.create_table(
        "app_user",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.Unicode(254), nullable=False),
        sa.Column("display_name", sa.Unicode(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _dt("created_at"),
        _dt("updated_at"),
        _dt("password_changed_at"),
        _dt("last_login_at", nullable=True),
        sa.CheckConstraint("role IN ('user', 'admin')", name="CK_app_user_role"),
        sa.CheckConstraint(
            "status IN ('active', 'deactivated', 'pending_deletion')", name="CK_app_user_status"
        ),
        schema=s,
    )
    op.create_index("UX_app_user_email", "app_user", ["email"], unique=True, schema=s)

    user_fk = f"{s}.app_user.user_id"
    op.create_table(
        "invitation",
        sa.Column("invitation_id", sa.Uuid(), primary_key=True),
        sa.Column("code_hash", sa.BINARY(32), nullable=False),
        sa.Column("email", sa.Unicode(254), nullable=False),
        sa.Column("note", sa.Unicode(200), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        _dt("created_at"),
        _dt("expires_at"),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey(user_fk), nullable=True),
        _dt("used_at", nullable=True),
        sa.Column("used_by_user_id", sa.Uuid(), sa.ForeignKey(user_fk), nullable=True),
        _dt("revoked_at", nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), sa.ForeignKey(user_fk), nullable=True),
        sa.UniqueConstraint("code_hash", name="UQ_invitation_code_hash"),
        sa.CheckConstraint(
            "status IN ('pending', 'used', 'revoked', 'expired')", name="CK_invitation_status"
        ),
        sa.CheckConstraint("expires_at > created_at", name="CK_invitation_expires"),
        schema=s,
    )
    op.create_index(
        "UX_invitation_pending_email",
        "invitation",
        ["email"],
        unique=True,
        schema=s,
        mssql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "IX_invitation_created_at", "invitation", [sa.text("created_at DESC")], schema=s
    )

    op.create_table(
        "password_reset_code",
        sa.Column("reset_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(user_fk), nullable=False),
        sa.Column("code_hash", sa.BINARY(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _dt("created_at"),
        _dt("expires_at"),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        _dt("used_at", nullable=True),
        sa.UniqueConstraint("code_hash", name="UQ_reset_code_hash"),
        sa.CheckConstraint(
            "status IN ('pending', 'used', 'superseded', 'expired')", name="CK_reset_status"
        ),
        schema=s,
    )
    op.create_index(
        "UX_reset_pending_user",
        "password_reset_code",
        ["user_id"],
        unique=True,
        schema=s,
        mssql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "user_session",
        sa.Column("session_hash", sa.BINARY(32), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(user_fk), nullable=False),
        _dt("created_at"),
        _dt("last_seen_at"),
        _dt("expires_at"),
        schema=s,
    )
    op.create_index("IX_user_session_user", "user_session", ["user_id"], schema=s)
    op.create_index("IX_user_session_expires", "user_session", ["expires_at"], schema=s)

    op.create_table(
        "login_attempt",
        sa.Column("attempt_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _dt("attempted_at"),
        sa.Column("email_hmac", sa.BINARY(32), nullable=True),
        sa.Column("ip_hmac", sa.BINARY(32), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('login', 'code_redeem', 'current_password')", name="CK_login_attempt_kind"
        ),
        schema=s,
    )
    op.create_index(
        "IX_login_attempt_email", "login_attempt", ["email_hmac", "attempted_at"], schema=s
    )
    op.create_index("IX_login_attempt_ip", "login_attempt", ["ip_hmac", "attempted_at"], schema=s)

    op.create_table(
        "audit_event",
        sa.Column("audit_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _dt("occurred_at"),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("subject_user_id", sa.Uuid(), nullable=True),
        sa.Column("ip_prefix", sa.String(50), nullable=True),
        sa.Column("details", sa.Unicode(1000), nullable=True),
        schema=s,
    )
    op.create_index(
        "IX_audit_event_occurred", "audit_event", [sa.text("occurred_at DESC")], schema=s
    )
    op.create_index(
        "IX_audit_event_subject", "audit_event", ["subject_user_id", "occurred_at"], schema=s
    )
    op.execute(
        f"""
CREATE TRIGGER [{s}].[TR_audit_event_immutable] ON [{s}].[audit_event]
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 51000, 'audit_event is insert-only', 1;
END
"""
    )
    op.execute(
        f"IF DATABASE_PRINCIPAL_ID(N'gh_app') IS NOT NULL "
        f"EXEC(N'DENY UPDATE, DELETE ON [{s}].[audit_event] TO [gh_app]')"
    )


def downgrade() -> None:
    s = _schema()
    op.execute(f"DROP TRIGGER IF EXISTS [{s}].[TR_audit_event_immutable]")
    op.drop_table("audit_event", schema=s)
    op.drop_table("login_attempt", schema=s)
    op.drop_table("user_session", schema=s)
    op.drop_table("password_reset_code", schema=s)
    op.drop_table("invitation", schema=s)
    op.drop_table("app_user", schema=s)
