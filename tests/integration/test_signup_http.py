import pytest
from sqlalchemy import select

from garmin_hub.db.schema import app_user, invitation
from garmin_hub.security.sessions import COOKIE_NAME

pytestmark = pytest.mark.integration

GENERIC = "El código no es válido o ha caducado."
PASSWORD = "luna-llena-sobre-el-puerto"


def step1(client, csrf_for, code):
    return client.post("/alta/codigo", data={"code": code, "csrf_token": csrf_for(client)})


def step2(client, csrf_for, code, **overrides):
    data = {
        "code": code,
        "display_name": "Ana Pérez",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "csrf_token": csrf_for(client),
    }
    data.update(overrides)
    return client.post("/alta", data=data, follow_redirects=False)


def invitation_status(engine):
    with engine.connect() as conn:
        return conn.execute(select(invitation.c.status)).scalar_one()


def test_signup_ok(client, csrf_for, make_invitation, engine, audit_rows) -> None:
    code = make_invitation("ana@club.test")
    assert client.get("/alta").status_code == 200
    r = step1(client, csrf_for, code.lower())
    assert r.status_code == 200
    assert 'value="ana@club.test"' in r.text and "readonly" in r.text
    r = step2(client, csrf_for, code)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert client.cookies.get(COOKIE_NAME)
    with engine.connect() as conn:
        user = conn.execute(select(app_user)).one()
        inv = conn.execute(select(invitation)).one()
    assert (user.role, user.status, user.email) == ("user", "active", "ana@club.test")
    assert inv.status == "used" and inv.used_by_user_id == user.user_id
    assert audit_rows("user.signed_up")[0]["subject_user_id"] == user.user_id
    home = client.get("/")
    assert home.status_code == 200 and "Ana Pérez" in home.text


@pytest.mark.parametrize("kind", ["used", "expired", "revoked", "missing"])
def test_invalid_codes(kind, client, csrf_for, make_invitation, clock, audit_rows) -> None:
    if kind == "used":
        code = make_invitation(status="used")
    elif kind == "revoked":
        code = make_invitation(status="revoked")
    elif kind == "expired":
        code = make_invitation(ttl_days=1)
        clock.advance(days=2)
    else:
        code = "AAAA-BBBB-CCCC-DDDD-EEEE"
    for r in (step1(client, csrf_for, code), step2(client, csrf_for, code)):
        assert r.status_code == 422
        assert GENERIC in r.text
    events = audit_rows("auth.code_redeem_failed")
    assert events and events[0]["details"] == {"kind": "invitation", "reason": "invalid"}


def test_manipulated_email(client, csrf_for, make_invitation, engine) -> None:
    code = make_invitation("ana@club.test")
    r = step2(client, csrf_for, code, email="otra@club.test")
    assert r.status_code == 422 and GENERIC in r.text
    assert invitation_status(engine) == "pending"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"password": "corta", "password_confirm": "corta"}, "al menos 12 caracteres"),
        ({"password": "a" * 11, "password_confirm": "a" * 11}, "al menos 12 caracteres"),
        ({"password_confirm": "otra-cosa-larga-aqui"}, "Las contraseñas no coinciden."),
        ({"display_name": "  "}, "El nombre debe tener entre 1 y 100 caracteres."),
    ],
)
def test_validation_does_not_consume(
    overrides, message, client, csrf_for, make_invitation, engine
) -> None:
    code = make_invitation()
    r = step2(client, csrf_for, code, **overrides)
    assert r.status_code == 422
    assert message in r.text
    assert invitation_status(engine) == "pending"


def test_email_registered_elsewhere(client, csrf_for, make_invitation, make_user, engine) -> None:
    code = make_invitation("ana@club.test")
    make_user(email="ana@club.test")
    r = step2(client, csrf_for, code)
    assert r.status_code == 422 and GENERIC in r.text
    assert invitation_status(engine) == "pending"
