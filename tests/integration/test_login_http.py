import pytest
from sqlalchemy import select, update

from garmin_hub.db.schema import app_user
from garmin_hub.security import passwords
from garmin_hub.security.sessions import COOKIE_NAME

pytestmark = pytest.mark.integration

GENERIC = "Correo o contraseña incorrectos."


def login(client, csrf_for, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": csrf_for(client)},
        follow_redirects=False,
    )


def test_login_ok(client, csrf_for, make_user, engine, audit_rows) -> None:
    user = make_user()
    r = login(client, csrf_for, user.email, user.password)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    for attr in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attr.lower() in cookie.lower()
    with engine.connect() as conn:
        assert conn.execute(select(app_user.c.last_login_at)).scalar_one() is not None
    event = audit_rows("auth.login_succeeded")[0]
    assert event["subject_user_id"] == user.user_id
    assert event["ip_prefix"] == "203.0.113.0/24"


@pytest.mark.parametrize("case", ["wrong", "missing", "deactivated", "pending_deletion"])
def test_failures_are_identical(case, client, csrf_for, make_user, audit_rows) -> None:
    status = {"deactivated": "deactivated", "pending_deletion": "pending_deletion"}.get(
        case, "active"
    )
    user = make_user(status=status)
    email = "nadie@club.test" if case == "missing" else user.email
    password = "contraseña-incorrecta" if case == "wrong" else user.password
    r = login(client, csrf_for, email, password)
    assert r.status_code == 422
    assert GENERIC in r.text
    reason = audit_rows("auth.login_failed")[0]["details"]["reason"]
    assert reason == ("inactive" if case == "deactivated" else "bad_credentials")


def test_missing_email_uses_dummy(client, csrf_for, monkeypatch) -> None:
    calls = []
    real = passwords.verify_dummy

    def spy(password=""):
        calls.append(1)
        return real(password)

    monkeypatch.setattr(passwords, "verify_dummy", spy)
    login(client, csrf_for, "nadie@club.test", "lo-que-sea-largo")
    assert calls == [1]


def test_email_normalized(client, csrf_for, make_user) -> None:
    user = make_user(email="ana@club.test")
    r = login(client, csrf_for, " Ana@Club.TEST ", user.password)
    assert r.status_code == 303


def test_new_session_each_login(make_client, csrf_for, make_user) -> None:
    user = make_user()
    a, b = make_client(), make_client()
    login(a, csrf_for, user.email, user.password)
    login(b, csrf_for, user.email, user.password)
    assert a.cookies.get(COOKIE_NAME) != b.cookies.get(COOKIE_NAME)


def test_rehash_when_needed(client, csrf_for, make_user, engine, monkeypatch) -> None:
    user = make_user()
    with engine.begin() as conn:
        conn.execute(update(app_user).values(password_hash=passwords.hash_password(user.password)))
    monkeypatch.setattr(passwords, "needs_rehash", lambda h: True)
    with engine.connect() as conn:
        before = conn.execute(select(app_user.c.password_hash)).scalar_one()
    login(client, csrf_for, user.email, user.password)
    with engine.connect() as conn:
        assert conn.execute(select(app_user.c.password_hash)).scalar_one() != before
