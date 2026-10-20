import pytest

from garmin_hub.accounts.audit import ALLOWED_DETAILS
from tests.integration.cycle import run_cycle

pytestmark = pytest.mark.integration


def test_catalog_complete_and_clean(
    engine, keys, clock, make_client, csrf_for, monkeypatch, audit_rows
) -> None:
    run_cycle(engine, keys, clock, make_client, csrf_for, monkeypatch)
    rows = audit_rows()
    emitted = {r["event_type"] for r in rows}
    assert emitted == set(ALLOWED_DETAILS), set(ALLOWED_DETAILS) - emitted
    for row in rows:
        blob = str(row["details"])
        assert "@" not in blob
        assert "Ana" not in blob and "Admin" not in blob
        prefix = row["ip_prefix"]
        assert prefix is None or prefix == "unknown" or "/" in prefix
    deleted = next(r for r in rows if r["event_type"] == "user.deleted")
    subject = deleted["subject_user_id"]
    for row in rows:
        if row["subject_user_id"] == subject:
            assert "ana@club.test" not in str(row)
