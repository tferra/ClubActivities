import pytest
from sqlalchemy import func, select, update

from garmin_hub.config import Settings
from garmin_hub.db.schema import app_user, user_session

pytestmark = pytest.mark.integration


def sessions(engine):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(user_session)).scalar_one()


def test_logout(client, make_user, login_as, csrf_for, engine, audit_rows) -> None:
    user = make_user()
    raw = login_as(client, user)
    r = client.post("/logout", data={"csrf_token": csrf_for(client)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert sessions(engine) == 0
    client.cookies.set("__Host-gh_session", raw)
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert audit_rows("auth.logout")[0]["subject_user_id"] == user.user_id


def test_idle_timeout(client, make_user, login_as, clock) -> None:
    login_as(client, make_user())
    clock.advance(minutes=29)
    assert client.get("/", follow_redirects=False).status_code == 200
    clock.advance(minutes=31)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_configured_idle_timeout(
    settings, secrets, engine, clock, fake_sleep, make_user, tmp_path
) -> None:
    from fastapi.testclient import TestClient

    from garmin_hub.security.sessions import COOKIE_NAME, create_session
    from garmin_hub.web.app import create_app

    custom = Settings(public_url="https://testserver", session_idle_minutes=10, log_dir=tmp_path)
    app = create_app(custom, secrets, engine=engine, clock=clock, sleep=fake_sleep)
    client = TestClient(app, base_url="https://testserver")
    user = make_user()
    with engine.begin() as conn:
        raw = create_session(conn, user.user_id, app.state.keys, custom, clock())
    client.cookies.set(COOKIE_NAME, raw)
    clock.advance(minutes=11)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_absolute_timeout(client, make_user, login_as, clock) -> None:
    login_as(client, make_user())
    for _ in range(12 * 4):
        clock.advance(minutes=15)
        r = client.get("/", follow_redirects=False)
    assert r.status_code == 303


def test_htmx_redirect(client) -> None:
    r = client.get("/", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers["hx-redirect"] == "/login"


def test_deactivation_cuts_session(client, make_user, login_as, engine) -> None:
    user = make_user()
    login_as(client, user)
    assert client.get("/").status_code == 200
    with engine.begin() as conn:
        conn.execute(update(app_user).values(status="deactivated"))
    assert client.get("/", follow_redirects=False).status_code == 303


def test_no_store(client, make_user, login_as) -> None:
    login_as(client, make_user())
    assert client.get("/").headers["cache-control"] == "no-store"
