import re

import pytest
from sqlalchemy import func, select, update

from garmin_hub.db.schema import app_user, user_session

pytestmark = pytest.mark.integration

GENERIC = "El código no es válido o ha caducado."
NEW = "barco-velero-en-la-bahia"
CODE_RE = re.compile(r"[0-9A-Z]{4}(?:-[0-9A-Z]{4}){4}")


@pytest.fixture
def admin_client(make_client, make_user, login_as):
    c = make_client("192.0.2.200")
    login_as(c, make_user(role="admin"))
    return c


def generate(admin_client, csrf_for, user):
    r = admin_client.post(
        f"/admin/usuarios/{user.user_id}/restablecimiento",
        data={"csrf_token": csrf_for(admin_client)},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "no se volverá a mostrar" in r.text
    return CODE_RE.search(r.text).group(0)


def reset(client, csrf_for, email, code, password=NEW):
    return client.post(
        "/restablecer",
        data={
            "email": email,
            "code": code,
            "password": password,
            "password_confirm": password,
            "csrf_token": csrf_for(client),
        },
        follow_redirects=False,
    )


def login(client, csrf_for, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": csrf_for(client)},
        follow_redirects=False,
    )


def test_full_reset(
    admin_client, make_client, csrf_for, make_user, login_as, engine, audit_rows
) -> None:
    user = make_user()
    session_client = make_client("192.0.2.1")
    login_as(session_client, user)
    code = generate(admin_client, csrf_for, user)
    anon = make_client("192.0.2.2")
    assert anon.get("/restablecer").status_code == 200
    r = reset(anon, csrf_for, user.email, code)
    assert r.status_code == 303 and r.headers["location"] == "/login?restablecida=1"
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(user_session)
                .where(user_session.c.user_id == user.user_id)
            ).scalar_one()
            == 0
        )
    assert login(anon, csrf_for, user.email, user.password).status_code == 422
    assert login(anon, csrf_for, user.email, NEW).status_code == 303
    assert audit_rows("reset.used")[0]["details"]["sessions_closed"] == 1
    again = make_client("192.0.2.3")
    r = reset(again, csrf_for, user.email, code)
    assert r.status_code == 422 and GENERIC in r.text
    assert audit_rows("auth.code_redeem_failed")[-1]["details"]["kind"] == "reset"


def test_wrong_email_expired_superseded(
    admin_client, make_client, csrf_for, make_user, clock
) -> None:
    user, other = make_user(), make_user()
    anon = make_client("192.0.2.4")
    old = generate(admin_client, csrf_for, user)
    new = generate(admin_client, csrf_for, user)
    assert GENERIC in reset(anon, csrf_for, user.email, old).text
    assert GENERIC in reset(anon, csrf_for, other.email, new).text
    clock.advance(hours=25)
    assert GENERIC in reset(anon, csrf_for, user.email, new).text


def test_deactivated_user_cannot_redeem(
    admin_client, make_client, csrf_for, make_user, engine
) -> None:
    user = make_user()
    code = generate(admin_client, csrf_for, user)
    with engine.begin() as conn:
        conn.execute(
            update(app_user).where(app_user.c.user_id == user.user_id).values(status="deactivated")
        )
    r = reset(make_client("192.0.2.5"), csrf_for, user.email, code)
    assert r.status_code == 422 and GENERIC in r.text


def test_ip_limit(make_client, csrf_for, make_user) -> None:
    user = make_user()
    attacker = make_client("198.51.100.66")
    for _ in range(20):
        reset(attacker, csrf_for, user.email, "AAAA-BBBB-CCCC-DDDD-EEEE")
    r = reset(attacker, csrf_for, user.email, "AAAA-BBBB-CCCC-DDDD-EEEE")
    assert r.status_code == 422


def test_generate_conflict_and_authz(admin_client, client, csrf_for, make_user, login_as) -> None:
    inactive = make_user(status="deactivated")
    r = admin_client.post(
        f"/admin/usuarios/{inactive.user_id}/restablecimiento",
        data={"csrf_token": csrf_for(admin_client)},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 409
    normal = make_user()
    login_as(client, normal)
    r = client.post(
        f"/admin/usuarios/{normal.user_id}/restablecimiento", data={"csrf_token": csrf_for(client)}
    )
    assert r.status_code == 404
