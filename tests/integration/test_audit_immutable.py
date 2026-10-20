import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from garmin_hub.accounts.audit import record_event
from garmin_hub.db.schema import audit_event

pytestmark = pytest.mark.integration


def test_record_event_inserts(engine, clock) -> None:
    with engine.begin() as conn:
        record_event(
            conn,
            "admin.created",
            actor_user_id=None,
            subject_user_id=None,
            ip_prefix="203.0.113.0/24",
            details={"via": "cli"},
            now=clock(),
        )
    with engine.connect() as conn:
        row = conn.execute(select(audit_event)).one()
    assert row.event_type == "admin.created"
    assert row.ip_prefix == "203.0.113.0/24"


@pytest.mark.mssql
def test_update_and_delete_fail(engine, clock) -> None:
    with engine.begin() as conn:
        record_event(
            conn,
            "auth.logout",
            actor_user_id=None,
            subject_user_id=None,
            ip_prefix=None,
            now=clock(),
        )
    for stmt in (update(audit_event).values(event_type="x"), delete(audit_event)):
        with pytest.raises(DBAPIError) as exc, engine.begin() as conn:
            conn.execute(stmt)
        assert "audit_event is insert-only" in str(exc.value)


def test_whitelist(engine, clock) -> None:
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="no permitidas"):
            record_event(
                conn,
                "admin.created",
                actor_user_id=None,
                subject_user_id=None,
                ip_prefix=None,
                details={"email": "a@b.test"},
                now=clock(),
            )
        with pytest.raises(ValueError, match="no permitido"):
            record_event(
                conn,
                "user.unknown",
                actor_user_id=None,
                subject_user_id=None,
                ip_prefix=None,
                now=clock(),
            )
        with pytest.raises(ValueError, match="red reducida"):
            record_event(
                conn,
                "auth.logout",
                actor_user_id=None,
                subject_user_id=None,
                ip_prefix="203.0.113.57",
                now=clock(),
            )
