from datetime import timedelta

import pytest
from sqlalchemy import select

from garmin_hub.accounts.invitations import (
    MSG_EMAIL_PENDING,
    MSG_TTL,
    create_invitation,
    list_invitations,
)
from garmin_hub.accounts.users import MSG_EMAIL_INVALID, MSG_EMAIL_TAKEN, ValidationFailed
from garmin_hub.config import Settings
from garmin_hub.db.schema import invitation

pytestmark = pytest.mark.integration


@pytest.fixture
def admin(make_user):
    return make_user(role="admin")


def create(engine, admin, keys, settings, clock, email="ana@club.test", **kw):
    with engine.begin() as conn:
        return create_invitation(
            conn,
            admin_id=admin.user_id,
            email=email,
            note=kw.get("note"),
            ttl_days=kw.get("ttl_days"),
            ip_prefix="203.0.113.0/24",
            keys=keys,
            settings=settings,
            now=clock(),
        )


def get(engine, invitation_id):
    with engine.connect() as conn:
        return conn.execute(
            select(invitation).where(invitation.c.invitation_id == invitation_id)
        ).one()


def test_default_ttl_and_storage(engine, admin, keys, settings, clock, audit_rows) -> None:
    inv_id, code = create(engine, admin, keys, settings, clock, email=" Ana@Club.TEST ")
    row = get(engine, inv_id)
    assert row.expires_at - row.created_at == timedelta(days=7)
    assert row.email == "ana@club.test"
    assert row.status == "pending"
    assert code not in str(tuple(row)) and code.replace("-", "") not in str(tuple(row))
    event = audit_rows("invitation.created")[0]
    assert event["details"] == {"invitation_id": str(inv_id), "ttl_days": 7}
    assert event["actor_user_id"] == admin.user_id


def test_configured_default_ttl(engine, admin, keys, tmp_path, clock) -> None:
    settings = Settings(public_url="https://testserver", invite_ttl_days=3, log_dir=tmp_path)
    inv_id, _ = create(engine, admin, keys, settings, clock)
    row = get(engine, inv_id)
    assert row.expires_at - row.created_at == timedelta(days=3)


def test_explicit_ttl_and_range(engine, admin, keys, settings, clock) -> None:
    inv_id, _ = create(engine, admin, keys, settings, clock, ttl_days=2)
    row = get(engine, inv_id)
    assert row.expires_at - row.created_at == timedelta(days=2)
    for bad in (0, 31):
        with pytest.raises(ValidationFailed) as exc:
            create(engine, admin, keys, settings, clock, email="x@club.test", ttl_days=bad)
        assert exc.value.message == MSG_TTL


def test_email_rejections(engine, admin, keys, settings, clock, make_user) -> None:
    with pytest.raises(ValidationFailed) as exc:
        create(engine, admin, keys, settings, clock, email="no-es-correo")
    assert exc.value.message == MSG_EMAIL_INVALID
    make_user(email="ya@club.test")
    with pytest.raises(ValidationFailed) as exc:
        create(engine, admin, keys, settings, clock, email="ya@club.test")
    assert exc.value.message == MSG_EMAIL_TAKEN
    create(engine, admin, keys, settings, clock, email="dos@club.test")
    with pytest.raises(ValidationFailed) as exc:
        create(engine, admin, keys, settings, clock, email="dos@club.test")
    assert exc.value.message == MSG_EMAIL_PENDING


def test_expired_pending_is_materialized(engine, admin, keys, settings, clock) -> None:
    old_id, _ = create(engine, admin, keys, settings, clock, ttl_days=1)
    clock.advance(days=2)
    new_id, _ = create(engine, admin, keys, settings, clock)
    assert get(engine, old_id).status == "expired"
    assert get(engine, new_id).status == "pending"


def test_list_effective_status(engine, admin, keys, settings, clock) -> None:
    create(engine, admin, keys, settings, clock, ttl_days=1, note="Club")
    with engine.connect() as conn:
        assert [i.status_label for i in list_invitations(conn, clock())] == ["Pendiente"]
        clock.advance(days=2)
        rows = list_invitations(conn, clock())
    assert rows[0].status_label == "Caducada"
    assert rows[0].note == "Club"
