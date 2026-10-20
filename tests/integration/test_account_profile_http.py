import pytest
from sqlalchemy import select

from garmin_hub.db.schema import app_user, login_attempt

pytestmark = pytest.mark.integration

NEW_PASSWORD = "barco-velero-en-la-bahia"


def post(client, csrf_for, path, **data):
    return client.post(path, data={**data, "csrf_token": csrf_for(client)}, follow_redirects=False)


def test_change_name(client, csrf_for, make_user, login_as, engine, audit_rows) -> None:
    user = make_user()
    login_as(client, user)
    r = post(client, csrf_for, "/cuenta/nombre", display_name="  Ana Nueva ")
    assert r.status_code == 303 and r.headers["location"].startswith("/cuenta")
    with engine.connect() as conn:
        assert conn.execute(select(app_user.c.display_name)).scalar_one() == "Ana Nueva"
    assert audit_rows("user.name_changed")
    assert "Ana Nueva" in client.get("/cuenta").text
    for bad in ("", "x" * 101):
        r = post(client, csrf_for, "/cuenta/nombre", display_name=bad)
        assert r.status_code == 422
        assert "El nombre debe tener entre 1 y 100 caracteres." in r.text


def test_change_password(make_client, csrf_for, make_user, login_as, audit_rows) -> None:
    user = make_user()
    a, b = make_client(), make_client()
    login_as(a, user)
    login_as(b, user)
    r = post(
        a,
        csrf_for,
        "/cuenta/contrasena",
        current_password=user.password,
        password=NEW_PASSWORD,
        password_confirm=NEW_PASSWORD,
    )
    assert r.status_code == 303
    assert a.get("/cuenta", follow_redirects=False).status_code == 200
    assert b.get("/cuenta", follow_redirects=False).status_code == 303
    assert audit_rows("user.password_changed")[0]["details"] == {"sessions_closed": 1}
    c = make_client("192.0.2.50")
    r = c.post(
        "/login",
        data={"email": user.email, "password": NEW_PASSWORD, "csrf_token": csrf_for(c)},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_wrong_current_password(client, csrf_for, make_user, login_as, engine, audit_rows) -> None:
    user = make_user()
    login_as(client, user)
    r = post(
        client,
        csrf_for,
        "/cuenta/contrasena",
        current_password="no-es-la-buena",
        password=NEW_PASSWORD,
        password_confirm=NEW_PASSWORD,
    )
    assert r.status_code == 422
    assert "La contraseña actual no es correcta." in r.text
    with engine.connect() as conn:
        kinds = [r.kind for r in conn.execute(select(login_attempt))]
    assert kinds == ["current_password"]
    assert audit_rows("user.password_change_failed")


def test_current_password_pair_limit(make_client, csrf_for, make_user, login_as) -> None:
    user = make_user()
    a = make_client("198.51.100.20")
    login_as(a, user)
    for _ in range(5):
        post(
            a,
            csrf_for,
            "/cuenta/contrasena",
            current_password="no-es-la-buena",
            password=NEW_PASSWORD,
            password_confirm=NEW_PASSWORD,
        )
    # el par queda bloqueado también para /login desde esa IP
    r = post(
        a,
        csrf_for,
        "/cuenta/contrasena",
        current_password=user.password,
        password=NEW_PASSWORD,
        password_confirm=NEW_PASSWORD,
    )
    assert r.status_code == 422
    fresh = make_client("198.51.100.20")
    r = post(fresh, csrf_for, "/login", email=user.email, password=user.password)
    assert r.status_code == 422
    # no cuentan para el límite por IP: otro correo entra desde esa IP
    other = make_user()
    r = post(fresh, csrf_for, "/login", email=other.email, password=other.password)
    assert r.status_code == 303


def test_new_password_invalid(client, csrf_for, make_user, login_as) -> None:
    user = make_user()
    login_as(client, user)
    r = post(
        client,
        csrf_for,
        "/cuenta/contrasena",
        current_password=user.password,
        password="corta",
        password_confirm="corta",
    )
    assert r.status_code == 422
    assert "al menos 12 caracteres" in r.text
