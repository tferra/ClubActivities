import secrets
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, insert, select

from garmin_hub.db.schema import app_user, invitation, password_reset_code, user_session

pytestmark = pytest.mark.integration


def delete(client, csrf_for, password, confirmation="ELIMINAR"):
    return client.post(
        "/cuenta/eliminar",
        data={
            "current_password": password,
            "confirmation": confirmation,
            "csrf_token": csrf_for(client),
        },
        follow_redirects=False,
    )


def count(engine, table, **where):
    stmt = select(func.count()).select_from(table)
    for column, value in where.items():
        stmt = stmt.where(table.c[column] == value)
    with engine.connect() as conn:
        return conn.execute(stmt).scalar_one()


@pytest.fixture
def user_with_data(make_user, engine, clock):
    admin = make_user(role="admin")
    user = make_user()
    now = clock()
    with engine.begin() as conn:
        conn.execute(
            insert(password_reset_code).values(
                reset_id=uuid.uuid4(),
                user_id=user.user_id,
                code_hash=secrets.token_bytes(32),
                status="pending",
                created_at=now,
                expires_at=now + timedelta(hours=24),
                created_by_user_id=admin.user_id,
            )
        )
        conn.execute(
            insert(invitation).values(
                invitation_id=uuid.uuid4(),
                code_hash=secrets.token_bytes(32),
                email=user.email,
                status="used",
                created_at=now,
                expires_at=now + timedelta(days=7),
                used_at=now,
                used_by_user_id=user.user_id,
                created_by_user_id=admin.user_id,
            )
        )
    return user


def test_page_explains(client, make_user, login_as) -> None:
    login_as(client, make_user())
    text = client.get("/cuenta/eliminar").text
    for item in ("cuentas Garmin", "ficheros crudos", "consentimientos", "membresías", "ELIMINAR"):
        assert item in text


@pytest.mark.parametrize(("password_ok", "confirmation"), [(False, "ELIMINAR"), (True, "borrar")])
def test_rejections(
    password_ok, confirmation, client, csrf_for, make_user, login_as, engine
) -> None:
    user = make_user()
    login_as(client, user)
    password = user.password if password_ok else "no-es-la-buena"
    r = delete(client, csrf_for, password, confirmation)
    assert r.status_code == 422
    assert count(engine, app_user, user_id=user.user_id) == 1


def test_last_admin_409(client, csrf_for, make_user, login_as, engine) -> None:
    admin = make_user(role="admin")
    login_as(client, admin)
    r = delete(client, csrf_for, admin.password)
    assert r.status_code == 409
    assert count(engine, app_user, user_id=admin.user_id) == 1


def test_delete_ok(
    client, csrf_for, user_with_data, login_as, engine, audit_rows, make_client
) -> None:
    user = user_with_data
    login_as(client, user)
    r = delete(client, csrf_for, user.password)
    assert r.status_code == 303 and r.headers["location"] == "/login?eliminada=1"
    assert count(engine, app_user, user_id=user.user_id) == 0
    assert count(engine, user_session, user_id=user.user_id) == 0
    assert count(engine, password_reset_code, user_id=user.user_id) == 0
    assert count(engine, invitation, used_by_user_id=user.user_id) == 0
    assert audit_rows("user.deletion_requested")[0]["details"] == {"by": "self"}
    deleted = audit_rows("user.deleted")[0]
    assert deleted["details"]["by"] == "self"
    assert deleted["details"]["steps"] == [
        "garmin_accounts",
        "delete_reset_codes",
        "null_invitation_refs",
    ]
    other = make_client("192.0.2.77")
    a = other.post(
        "/login",
        data={"email": user.email, "password": user.password, "csrf_token": csrf_for(other)},
    )
    b = other.post(
        "/login",
        data={"email": "nadie@club.test", "password": user.password, "csrf_token": csrf_for(other)},
    )
    assert a.status_code == b.status_code == 422
    assert (
        audit_rows("auth.login_failed")[-2]["details"]
        == audit_rows("auth.login_failed")[-1]["details"]
    )
