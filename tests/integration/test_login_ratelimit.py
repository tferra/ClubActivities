import inspect

import pytest
from sqlalchemy import select

from garmin_hub.db.schema import login_attempt
from garmin_hub.security.ratelimit import Kind, record_attempt
from garmin_hub.web.routes import auth

pytestmark = pytest.mark.integration

GENERIC = "Correo o contraseña incorrectos."


def login(client, csrf_for, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": csrf_for(client)},
        follow_redirects=False,
    )


def test_pair_block(make_client, csrf_for, make_user, audit_rows) -> None:
    user = make_user()
    a = make_client("198.51.100.1")
    for _ in range(5):
        assert login(a, csrf_for, user.email, "mal-mal-mal-mal").status_code == 422
    r = login(a, csrf_for, user.email, user.password)
    assert r.status_code == 422 and GENERIC in r.text
    assert audit_rows("auth.login_failed")[-1]["details"]["reason"] == "blocked_pair"
    b = make_client("198.51.100.2")
    assert login(b, csrf_for, user.email, user.password).status_code == 303


def test_success_resets_pair(make_client, csrf_for, make_user) -> None:
    user = make_user()
    a = make_client("198.51.100.1")
    for _ in range(4):
        login(a, csrf_for, user.email, "mal-mal-mal-mal")
    assert login(a, csrf_for, user.email, user.password).status_code == 303
    a.cookies.clear()
    for _ in range(4):
        login(a, csrf_for, user.email, "mal-mal-mal-mal")
    assert login(a, csrf_for, user.email, user.password).status_code == 303


def test_ip_block(make_client, csrf_for, make_user) -> None:
    user = make_user()
    a = make_client("198.51.100.1")
    for i in range(20):
        login(a, csrf_for, f"otro{i}@club.test", "mal-mal-mal-mal")
    assert login(a, csrf_for, user.email, user.password).status_code == 422


def test_email_soft_limit(
    make_client, csrf_for, make_user, engine, keys, clock, fake_sleep, audit_rows
) -> None:
    user = make_user()
    with engine.begin() as conn:
        for i in range(49):
            record_attempt(
                conn,
                email=user.email,
                ip=f"192.0.2.{i}",
                kind=Kind.LOGIN,
                succeeded=False,
                keys=keys,
                now=clock(),
            )
    c = make_client("198.51.100.9")
    login(c, csrf_for, user.email, "mal-mal-mal-mal")  # n=49 antes → sin retardo, ahora 50
    assert fake_sleep.calls == []
    r = login(c, csrf_for, user.email, user.password)  # n=50 → 0,5 s
    assert fake_sleep.calls == [0.5]
    assert r.status_code == 303
    assert len(audit_rows("auth.email_soft_limit")) == 1
    with engine.begin() as conn:
        for i in range(20):
            record_attempt(
                conn,
                email=user.email,
                ip=f"192.0.3.{i}",
                kind=Kind.LOGIN,
                succeeded=False,
                keys=keys,
                now=clock(),
            )
    c2 = make_client("198.51.100.10")
    login(c2, csrf_for, user.email, user.password)
    assert fake_sleep.calls[-1] == 10
    assert len(audit_rows("auth.email_soft_limit")) == 1


def test_login_route_is_coroutine() -> None:
    assert inspect.iscoroutinefunction(auth.login_submit)
    assert "time.sleep" not in inspect.getsource(auth)


def test_pseudonymized(make_client, csrf_for, make_user, engine) -> None:
    user = make_user()
    login(make_client("198.51.100.1"), csrf_for, user.email, "mal-mal-mal-mal")
    with engine.connect() as conn:
        row = conn.execute(select(login_attempt)).one()
    assert user.email.encode() not in row.email_hmac
    assert set(login_attempt.c.keys()) == {
        "attempt_id",
        "attempted_at",
        "email_hmac",
        "ip_hmac",
        "kind",
        "succeeded",
    }
