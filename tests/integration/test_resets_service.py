from datetime import timedelta

import pytest
from sqlalchemy import select, update

from garmin_hub.accounts.invitations import InvalidCode
from garmin_hub.accounts.resets import create_reset_code, redeem_reset_code
from garmin_hub.accounts.users import Conflict, deactivate_user, reactivate_user
from garmin_hub.db.schema import app_user, password_reset_code

pytestmark = pytest.mark.integration

NEW = "barco-velero-en-la-bahia"


def create(engine, admin, user, keys, settings, clock):
    with engine.begin() as conn:
        return create_reset_code(
            conn,
            admin_id=admin.user_id,
            user_id=user.user_id,
            keys=keys,
            settings=settings,
            ip_prefix=None,
            now=clock(),
        )


def redeem(engine, user, code, keys, clock):
    with engine.begin() as conn:
        return redeem_reset_code(
            conn,
            email=user.email,
            code=code,
            new_password=NEW,
            keys=keys,
            ip_prefix=None,
            now=clock(),
        )


def statuses(engine):
    with engine.connect() as conn:
        return [
            r.status
            for r in conn.execute(
                select(password_reset_code).order_by(password_reset_code.c.created_at)
            )
        ]


def test_create_and_supersede(engine, make_user, keys, settings, clock, audit_rows) -> None:
    admin, user = make_user(role="admin"), make_user()
    code = create(engine, admin, user, keys, settings, clock)
    with engine.connect() as conn:
        row = conn.execute(select(password_reset_code)).one()
    assert row.expires_at - row.created_at == timedelta(hours=24)
    assert code.replace("-", "").encode() not in row.code_hash
    assert audit_rows("reset.created")[0]["details"] == {"reset_id": str(row.reset_id)}
    clock.advance(minutes=1)
    create(engine, admin, user, keys, settings, clock)
    assert statuses(engine) == ["superseded", "pending"]
    with pytest.raises(InvalidCode):
        redeem(engine, user, code, keys, clock)


def test_reject_inactive(engine, make_user, keys, settings, clock) -> None:
    admin, user = make_user(role="admin"), make_user(status="deactivated")
    with pytest.raises(Conflict):
        create(engine, admin, user, keys, settings, clock)


def test_deactivation_expires_codes(engine, make_user, keys, settings, clock) -> None:
    admin, user = make_user(role="admin"), make_user()
    code = create(engine, admin, user, keys, settings, clock)
    with engine.begin() as conn:
        deactivate_user(
            conn, admin_id=admin.user_id, user_id=user.user_id, ip_prefix=None, now=clock()
        )
        reactivate_user(
            conn, admin_id=admin.user_id, user_id=user.user_id, ip_prefix=None, now=clock()
        )
    assert statuses(engine) == ["expired"]
    with pytest.raises(InvalidCode):
        redeem(engine, user, code, keys, clock)


def test_pending_deletion_cannot_redeem(engine, make_user, keys, settings, clock) -> None:
    admin, user = make_user(role="admin"), make_user()
    code = create(engine, admin, user, keys, settings, clock)
    with engine.begin() as conn:
        conn.execute(
            update(app_user)
            .where(app_user.c.user_id == user.user_id)
            .values(status="pending_deletion")
        )
    with pytest.raises(InvalidCode):
        redeem(engine, user, code, keys, clock)
