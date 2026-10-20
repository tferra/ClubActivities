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
    expected = {name for name in ALLOWED_DETAILS if not name.startswith("garmin.")}
    assert emitted == expected, expected - emitted
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


GARMIN_EVENTS = {
    "garmin.notice_accepted": {"notice_version"},
    "garmin.account_linked": {"garmin_account_id", "recovered", "mfa"},
    "garmin.link_failed": {"reason"},
    "garmin.reauthenticated": {"garmin_account_id", "mfa"},
    "garmin.reauth_failed": {"garmin_account_id", "reason"},
    "garmin.status_changed": {"garmin_account_id", "from", "to", "via", "error_code"},
    "garmin.account_checked": {"garmin_account_id", "result"},
    "garmin.account_unlinked": {"garmin_account_id", "data"},
    "garmin.data_deletion_requested": {"garmin_account_id"},
    "garmin.account_deletion_step_failed": {"garmin_account_id", "step"},
    "garmin.account_deleted": {"garmin_account_id", "steps"},
}


def test_garmin_events_whitelisted_with_exact_keys() -> None:
    garmin = {k: set(v) for k, v in ALLOWED_DETAILS.items() if k.startswith("garmin.")}
    assert garmin == GARMIN_EVENTS


@pytest.mark.parametrize("event_type", sorted(GARMIN_EVENTS))
def test_garmin_events_reject_other_keys(engine, clock, event_type) -> None:
    from garmin_hub.accounts.audit import record_event

    for bad in ("alias", "email", "garmin_profile_id", "password"):
        with pytest.raises(ValueError), engine.begin() as conn:
            record_event(
                conn,
                event_type,
                actor_user_id=None,
                subject_user_id=None,
                ip_prefix=None,
                details={bad: "x"},
                now=clock(),
            )
