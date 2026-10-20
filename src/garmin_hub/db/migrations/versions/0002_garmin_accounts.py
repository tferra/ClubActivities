"""garmin accounts: garmin_account, garmin_token, data_notice_acceptance, garmin_login_failure

Revision ID: 0002_garmin_accounts
Revises: 0001_user_access
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mssql import DATETIME2, VARBINARY

revision = "0002_garmin_accounts"
down_revision = "0001_user_access"
branch_labels = None
depends_on = None

ACTIVE_FILTER = "status IN ('valid', 'reauth_required', 'error')"
LIVE_FILTER = "status IN ('valid', 'reauth_required', 'error', 'unlinked')"
STATUS_FIELDS_CHECK = (
    "((status = 'error' AND error_code IS NOT NULL) OR (status <> 'error' AND error_code IS NULL))"
    " AND (status <> 'unlinked' OR unlinked_at IS NOT NULL)"
    " AND (status <> 'deleting' OR deletion_requested_at IS NOT NULL)"
)


def _schema() -> str:
    return op.get_context().opts["version_table_schema"]


def _dt(name, nullable=False):
    return sa.Column(name, DATETIME2(3), nullable=nullable)


def upgrade() -> None:
    s = _schema()
    user_fk = f"{s}.app_user.user_id"
    op.create_table(
        "garmin_account",
        sa.Column("garmin_account_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(user_fk), nullable=False),
        sa.Column("alias", sa.Unicode(50), nullable=False),
        sa.Column("alias_key", sa.Unicode(50), nullable=False),
        sa.Column("garmin_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        _dt("linked_at"),
        _dt("last_login_at"),
        _dt("last_sync_at", nullable=True),
        _dt("last_checked_at", nullable=True),
        _dt("last_check_started_at", nullable=True),
        _dt("request_lease_until", nullable=True),
        _dt("unlinked_at", nullable=True),
        _dt("deletion_requested_at", nullable=True),
        _dt("created_at"),
        _dt("updated_at"),
        sa.CheckConstraint(
            "status IN ('valid', 'reauth_required', 'error', 'unlinked', 'deleting')",
            name="CK_garmin_account_status",
        ),
        sa.CheckConstraint(
            "error_code IN ('token_undecryptable', 'identity_mismatch')",
            name="CK_garmin_account_error_code",
        ),
        sa.CheckConstraint(STATUS_FIELDS_CHECK, name="CK_garmin_account_status_fields"),
        schema=s,
    )
    op.create_index(
        "UX_garmin_account_profile_active",
        "garmin_account",
        ["garmin_profile_id"],
        unique=True,
        schema=s,
        mssql_where=sa.text(ACTIVE_FILTER),
    )
    op.create_index(
        "UX_garmin_account_user_profile",
        "garmin_account",
        ["user_id", "garmin_profile_id"],
        unique=True,
        schema=s,
        mssql_where=sa.text(LIVE_FILTER),
    )
    op.create_index(
        "UX_garmin_account_user_alias",
        "garmin_account",
        ["user_id", "alias_key"],
        unique=True,
        schema=s,
        mssql_where=sa.text(LIVE_FILTER),
    )
    op.create_index("IX_garmin_account_user", "garmin_account", ["user_id", "created_at"], schema=s)

    op.create_table(
        "garmin_token",
        sa.Column(
            "garmin_account_id",
            sa.Uuid(),
            sa.ForeignKey(f"{s}.garmin_account.garmin_account_id"),
            primary_key=True,
        ),
        sa.Column("ciphertext", VARBINARY("max"), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        _dt("issued_at"),
        _dt("updated_at"),
        sa.CheckConstraint("key_version > 0", name="CK_garmin_token_key_version"),
        schema=s,
    )

    op.create_table(
        "data_notice_acceptance",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(user_fk), primary_key=True),
        sa.Column("notice_version", sa.Integer(), primary_key=True),
        _dt("accepted_at"),
        sa.CheckConstraint("notice_version > 0", name="CK_data_notice_acceptance_version"),
        schema=s,
    )

    op.create_table(
        "garmin_login_failure",
        sa.Column("failure_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(user_fk), nullable=False),
        _dt("failed_at"),
        schema=s,
    )
    op.create_index(
        "IX_garmin_login_failure_user",
        "garmin_login_failure",
        ["user_id", "failed_at"],
        schema=s,
    )


def downgrade() -> None:
    s = _schema()
    op.drop_table("garmin_login_failure", schema=s)
    op.drop_table("data_notice_acceptance", schema=s)
    op.drop_table("garmin_token", schema=s)
    op.drop_table("garmin_account", schema=s)
