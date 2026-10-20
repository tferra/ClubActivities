import pytest
from sqlalchemy import select

from garmin_hub.db.schema import app_user

pytestmark = pytest.mark.integration


@pytest.fixture
def admin(make_user):
    return make_user(role="admin")


@pytest.fixture
def admin_client(make_client, admin, login_as):
    c = make_client()
    login_as(c, admin)
    return c


def exists(engine, user_id):
    with engine.connect() as conn:
        return (
            conn.execute(select(app_user).where(app_user.c.user_id == user_id)).first() is not None
        )


def test_delete_deactivated_user(
    admin_client, admin, csrf_for, make_user, engine, audit_rows
) -> None:
    user = make_user(status="deactivated")
    page = admin_client.get(f"/admin/usuarios/{user.user_id}/eliminar")
    assert page.status_code == 200 and "correo" in page.text
    r = admin_client.post(
        f"/admin/usuarios/{user.user_id}/eliminar",
        data={"confirmation_email": " " + user.email.upper(), "csrf_token": csrf_for(admin_client)},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/admin/usuarios"
    assert not exists(engine, user.user_id)
    deleted = audit_rows("user.deleted")[0]
    assert deleted["details"]["by"] == "admin"
    assert deleted["actor_user_id"] == admin.user_id


def test_wrong_email_422(admin_client, csrf_for, make_user, engine) -> None:
    user = make_user(status="deactivated")
    r = admin_client.post(
        f"/admin/usuarios/{user.user_id}/eliminar",
        data={"confirmation_email": "otro@club.test", "csrf_token": csrf_for(admin_client)},
    )
    assert r.status_code == 422
    assert exists(engine, user.user_id)


@pytest.mark.parametrize(("role", "status"), [("user", "active"), ("admin", "deactivated")])
def test_conflicts(role, status, admin_client, csrf_for, make_user, engine) -> None:
    user = make_user(role=role, status=status)
    assert admin_client.get(f"/admin/usuarios/{user.user_id}/eliminar").status_code == 409
    r = admin_client.post(
        f"/admin/usuarios/{user.user_id}/eliminar",
        data={"confirmation_email": user.email, "csrf_token": csrf_for(admin_client)},
    )
    assert r.status_code == 409
    assert exists(engine, user.user_id)
