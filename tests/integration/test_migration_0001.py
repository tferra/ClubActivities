import secrets

import pytest
from sqlalchemy import create_engine, inspect, text

from garmin_hub.db.migrate import current_revision, head_revision, run_downgrade, run_upgrade

pytestmark = [pytest.mark.integration, pytest.mark.mssql]

TABLES = {
    "app_user",
    "invitation",
    "password_reset_code",
    "user_session",
    "login_attempt",
    "audit_event",
}
INDEXES = {
    "UX_app_user_email",
    "UX_invitation_pending_email",
    "IX_invitation_created_at",
    "UX_reset_pending_user",
    "IX_user_session_user",
    "IX_user_session_expires",
    "IX_login_attempt_email",
    "IX_login_attempt_ip",
    "IX_audit_event_occurred",
    "IX_audit_event_subject",
}


def test_upgrade_downgrade_upgrade() -> None:
    import os

    engine = create_engine(os.environ["GARMIN_HUB_TEST_DB_URL"])
    schema = f"gh_m_{secrets.token_hex(4)}"
    try:
        assert run_upgrade(engine, schema) == head_revision()
        insp = inspect(engine)
        assert set(insp.get_table_names(schema=schema)) >= TABLES
        found = {ix["name"] for t in TABLES for ix in insp.get_indexes(t, schema=schema)}
        assert found >= INDEXES
        with engine.connect() as conn:
            trigger = conn.execute(
                text(
                    "SELECT name FROM sys.triggers WHERE name = 'TR_audit_event_immutable' "
                    "AND parent_id = OBJECT_ID(:t)"
                ),
                {"t": f"{schema}.audit_event"},
            ).scalar()
        assert trigger == "TR_audit_event_immutable"

        run_downgrade(engine, schema)
        insp = inspect(engine)
        assert not TABLES & set(insp.get_table_names(schema=schema))
        with engine.connect() as conn:
            assert current_revision(conn, schema) is None

        assert run_upgrade(engine, schema) == head_revision()
        # idempotente
        assert run_upgrade(engine, schema) == head_revision()
    finally:
        run_downgrade(engine, schema)
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS [{schema}].[alembic_version]"))
            conn.execute(text(f"DROP SCHEMA [{schema}]"))
        engine.dispose()
