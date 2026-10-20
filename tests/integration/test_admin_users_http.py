import pytest
from sqlalchemy import select

from garmin_hub.db.schema import app_user

pytestmark = pytest.mark.integration


@pytest.fixture
def admin(make_user):
    return make_user(role="admin", display_name="Admin Uno")


@pytest.fixture
def admin_client(make_client, admin, login_as):
    c = make_client()
    login_as(c, admin)
    return c


def act(client, csrf_for, user_id, action):
    return client.post(
        f"/admin/usuarios/{user_id}/{action}",
        data={"csrf_token": csrf_for(client)},
        headers={"HX-Request": "true"},
    )


def status_of(engine, user_id):
    with engine.connect() as conn:
        return conn.execute(
            select(app_user.c.status).where(app_user.c.user_id == user_id)
        ).scalar_one()


def test_list(admin_client, make_user) -> None:
    user = make_user(display_name="Bea Gómez", email="bea@club.test")
    r = admin_client.get("/admin/usuarios")
    assert r.status_code == 200
    for text in ("Bea Gómez", "bea@club.test", "Usuario", "Activo", "Administrador"):
        assert text in r.text
    assert str(user.user_id) in r.text


def test_deactivate_and_reactivate(
    admin_client, csrf_for, make_user, make_client, login_as, engine, audit_rows
) -> None:
    user = make_user()
    victim = make_client("192.0.2.99")
    login_as(victim, user)
    r = act(admin_client, csrf_for, user.user_id, "desactivar")
    assert r.status_code == 200 and "Desactivado" in r.text
    assert status_of(engine, user.user_id) == "deactivated"
    assert victim.get("/", follow_redirects=False).status_code == 303
    assert audit_rows("user.deactivated")[0]["details"] == {
        "sessions_closed": 1,
        "resets_expired": 0,
    }
    login = victim.post(
        "/login",
        data={"email": user.email, "password": user.password, "csrf_token": csrf_for(victim)},
        follow_redirects=False,
    )
    assert login.status_code == 422

    r = act(admin_client, csrf_for, user.user_id, "reactivar")
    assert r.status_code == 200 and "Activo" in r.text
    assert audit_rows("user.reactivated")
    login = victim.post(
        "/login",
        data={"email": user.email, "password": user.password, "csrf_token": csrf_for(victim)},
        follow_redirects=False,
    )
    assert login.status_code == 303


def test_conflicts(admin_client, csrf_for, admin, make_user) -> None:
    user = make_user()
    assert act(admin_client, csrf_for, user.user_id, "reactivar").status_code == 409
    r = act(admin_client, csrf_for, admin.user_id, "desactivar")
    assert r.status_code == 409 and "No puedes desactivarte a ti mismo." in r.text


def test_last_admin(make_client, make_user, login_as, csrf_for, engine) -> None:
    a = make_user(role="admin")
    b = make_user(role="admin")
    ca = make_client()
    login_as(ca, a)
    assert act(ca, csrf_for, b.user_id, "desactivar").status_code == 200
    # ya solo queda A; otro admin (desactivado) no puede actuar, A no puede desactivarse
    assert act(ca, csrf_for, a.user_id, "desactivar").status_code == 409
    assert status_of(engine, a.user_id) == "active"
