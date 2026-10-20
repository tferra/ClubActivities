import os
import secrets
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from garmin_hub.db.migrate import current_revision, run_downgrade, run_upgrade

pytestmark = [pytest.mark.integration, pytest.mark.mssql]

TABLES_002 = {
    "garmin_account": {
        "garmin_account_id",
        "user_id",
        "alias",
        "alias_key",
        "garmin_profile_id",
        "status",
        "error_code",
        "linked_at",
        "last_login_at",
        "last_sync_at",
        "last_checked_at",
        "last_check_started_at",
        "request_lease_until",
        "unlinked_at",
        "deletion_requested_at",
        "created_at",
        "updated_at",
    },
    "garmin_token": {"garmin_account_id", "ciphertext", "key_version", "issued_at", "updated_at"},
    "data_notice_acceptance": {"user_id", "notice_version", "accepted_at"},
    "garmin_login_failure": {"failure_id", "user_id", "failed_at"},
}
TABLES_001 = {
    "app_user",
    "invitation",
    "password_reset_code",
    "user_session",
    "login_attempt",
    "audit_event",
}
INDEXES = {
    "UX_garmin_account_profile_active",
    "UX_garmin_account_user_profile",
    "UX_garmin_account_user_alias",
    "IX_garmin_account_user",
    "IX_garmin_login_failure_user",
}
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC).replace(tzinfo=None)


@pytest.fixture
def schema_engine():
    engine = create_engine(os.environ["GARMIN_HUB_TEST_DB_URL"])
    schema = f"gh_m_{secrets.token_hex(4)}"
    yield engine, schema
    run_downgrade(engine, schema)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS [{schema}].[alembic_version]"))
        conn.execute(text(f"DROP SCHEMA [{schema}]"))
    engine.dispose()


def test_upgrade_downgrade_upgrade(schema_engine) -> None:
    engine, schema = schema_engine
    assert run_upgrade(engine, schema) == "0002_garmin_accounts"
    insp = inspect(engine)
    for table, columns in TABLES_002.items():
        assert {c["name"] for c in insp.get_columns(table, schema=schema)} == columns
    found = {ix["name"] for t in TABLES_002 for ix in insp.get_indexes(t, schema=schema)}
    assert found >= INDEXES

    run_downgrade(engine, schema, "0001_user_access")
    insp = inspect(engine)
    names = set(insp.get_table_names(schema=schema))
    assert not set(TABLES_002) & names
    assert names >= TABLES_001
    with engine.connect() as conn:
        assert current_revision(conn, schema) == "0001_user_access"

    assert run_upgrade(engine, schema) == "0002_garmin_accounts"


def _insert_user(conn, schema) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO [{schema}].[app_user] (user_id, email, display_name, password_hash, "
            "role, status, created_at, updated_at, password_changed_at) VALUES "
            "(:id, :email, 'X', 'h', 'user', 'active', :now, :now, :now)"
        ),
        {"id": user_id, "email": f"{user_id}@club.test", "now": NOW},
    )
    return user_id


def _insert_account(conn, schema, user_id, profile_id, alias, status, **extra) -> None:
    values = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "alias": alias,
        "alias_key": alias.casefold(),
        "profile": profile_id,
        "status": status,
        "now": NOW,
        "error_code": extra.get("error_code"),
        "unlinked_at": extra.get("unlinked_at"),
        "deletion_requested_at": extra.get("deletion_requested_at"),
    }
    conn.execute(
        text(
            f"INSERT INTO [{schema}].[garmin_account] (garmin_account_id, user_id, alias, "
            "alias_key, garmin_profile_id, status, error_code, linked_at, last_login_at, "
            "unlinked_at, deletion_requested_at, created_at, updated_at) VALUES (:id, :user_id, "
            ":alias, :alias_key, :profile, :status, :error_code, :now, :now, :unlinked_at, "
            ":deletion_requested_at, :now, :now)"
        ),
        values,
    )


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("error", {}),
        ("unlinked", {}),
        ("deleting", {}),
        ("valid", {"error_code": "identity_mismatch"}),
    ],
)
def test_status_fields_check(schema_engine, status, extra) -> None:
    engine, schema = schema_engine
    run_upgrade(engine, schema)
    with engine.begin() as conn:
        user_id = _insert_user(conn, schema)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_account(conn, schema, user_id, 1, "A", status, **extra)


def test_filtered_unique_indexes(schema_engine) -> None:
    engine, schema = schema_engine
    run_upgrade(engine, schema)
    with engine.begin() as conn:
        ana, bea = _insert_user(conn, schema), _insert_user(conn, schema)
        _insert_account(conn, schema, ana, 1, "Mía", "valid")
    # otra fila activa con la misma identidad, aunque sea de otro usuario
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_account(conn, schema, bea, 1, "Suya", "valid")
    # alias repetido del mismo usuario, sin distinguir mayúsculas
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_account(conn, schema, ana, 2, "MÍA", "valid")
    with engine.begin() as conn:
        # las filas en deleting no cuentan para ningún índice
        _insert_account(conn, schema, ana, 1, "Mía", "deleting", deletion_requested_at=NOW)
        # unlinked: libera la identidad activa, pero no el par usuario-identidad
        _insert_account(conn, schema, bea, 3, "Vieja", "unlinked", unlinked_at=NOW)
        _insert_account(conn, schema, ana, 3, "Nueva", "valid")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_account(conn, schema, bea, 3, "Otra", "valid")
