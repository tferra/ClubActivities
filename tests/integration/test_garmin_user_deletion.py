import pytest
from sqlalchemy import func, select

from garmin_hub.db.schema import (
    data_notice_acceptance,
    garmin_account,
    garmin_login_failure,
    garmin_token,
)
from garmin_hub.garmin_accounts import ratelimit

pytestmark = pytest.mark.integration

TABLES = (garmin_account, garmin_token, data_notice_acceptance, garmin_login_failure)


def counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one() for t in TABLES
        }


def seed(engine, clock, user, make_garmin_account, accept_notice) -> None:
    accept_notice(user.user_id)
    make_garmin_account(user.user_id, alias="Activa")
    make_garmin_account(user.user_id, alias="Vieja", status="unlinked")
    with engine.begin() as conn:
        ratelimit.record_failure(conn, user.user_id, clock())


def test_self_deletion_removes_garmin_data(
    client,
    make_user,
    login_as,
    form_post,
    engine,
    clock,
    make_garmin_account,
    accept_notice,
    audit_rows,
) -> None:
    other = make_user()
    seed(engine, clock, other, make_garmin_account, accept_notice)
    user = make_user()
    seed(engine, clock, user, make_garmin_account, accept_notice)
    login_as(client, user)
    r = form_post(
        client,
        "/cuenta/eliminar",
        {"current_password": user.password, "confirmation": "ELIMINAR"},
    )
    assert r.status_code == 303 and r.headers["location"] == "/login?eliminada=1"
    assert counts(engine) == {
        "garmin_account": 2,
        "garmin_token": 1,
        "data_notice_acceptance": 1,
        "garmin_login_failure": 1,
    }  # solo quedan las de `other`
    (deleted,) = audit_rows("user.deleted")
    assert "garmin_accounts" in deleted["details"]["steps"]
    assert len(audit_rows("garmin.account_deleted")) == 2


def test_admin_deletion_removes_garmin_data(
    make_client, make_user, login_as, form_post, engine, clock, make_garmin_account, accept_notice
) -> None:
    user = make_user(status="deactivated")
    seed(engine, clock, user, make_garmin_account, accept_notice)
    admin = make_user(role="admin")
    client = make_client()
    login_as(client, admin)
    r = form_post(
        client,
        f"/admin/usuarios/{user.user_id}/eliminar",
        {"confirmation_email": user.email},
    )
    assert r.status_code in (200, 303)
    assert counts(engine) == dict.fromkeys(counts(engine), 0)
