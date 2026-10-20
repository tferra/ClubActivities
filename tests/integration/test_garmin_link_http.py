import pytest
from sqlalchemy import select

from garmin_hub.db.schema import garmin_token
from garmin_hub.garmin.fake import FAKE_PASSWORD

pytestmark = pytest.mark.integration

LINK = "/cuentas-garmin/vincular"


def link(form_post, client, alias="Principal", email="ok+1@example.test", password=FAKE_PASSWORD):
    return form_post(
        client, LINK, {"alias": alias, "garmin_email": email, "garmin_password": password}
    )


def test_get_form(client, garmin_user) -> None:
    r = client.get(LINK)
    assert r.status_code == 200
    assert 'name="garmin_password"' in r.text and "no se guarda" in r.text


def test_link_ok(client, garmin_user, form_post, garmin_rows, engine, app, clock) -> None:
    r = link(form_post, client)
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?vinculada=1"
    (row,) = garmin_rows(garmin_user.user_id)
    assert row["status"] == "valid" and row["alias"] == "Principal"
    assert row["garmin_profile_id"] == 1
    assert row["last_login_at"] == clock() and row["last_sync_at"] is None
    with engine.connect() as conn:
        token = conn.execute(select(garmin_token)).one()
    assert token.garmin_account_id == row["garmin_account_id"]
    assert token.key_version == app.state.token_cipher.current_version


def test_bad_password(client, garmin_user, form_post, garmin_rows) -> None:
    r = link(form_post, client, password="mala")
    assert r.status_code == 422
    assert "Garmin no acepta ese correo o contraseña." in r.text
    assert garmin_rows() == []


@pytest.mark.parametrize(
    ("email", "message"),
    [
        ("down@example.test", "No se ha podido conectar con Garmin; inténtalo más tarde."),
        (
            "ratelimit@example.test",
            "Garmin está limitando las peticiones; inténtalo dentro de un rato.",
        ),
        (
            "blocked@example.test",
            "Garmin ha bloqueado temporalmente el inicio de sesión; inténtalo más tarde.",
        ),
    ],
)
def test_transient_garmin_errors(client, garmin_user, form_post, garmin_rows, email, message):
    r = link(form_post, client, email=email)
    assert r.status_code == 422 and message in r.text
    assert garmin_rows() == []


@pytest.mark.parametrize("alias", ["", "   ", "x" * 51])
def test_invalid_alias_does_not_call_garmin(client, garmin_user, form_post, fake_garmin, alias):
    r = link(form_post, client, alias=alias)
    assert r.status_code == 422
    assert "El alias debe tener entre 1 y 50 caracteres." in r.text
    assert fake_garmin.calls == []


def test_alias_is_trimmed_and_50_chars_allowed(client, garmin_user, form_post, garmin_rows):
    assert link(form_post, client, alias=f"  {'x' * 50}  ").status_code == 303
    assert garmin_rows()[0]["alias"] == "x" * 50


def test_same_identity_same_user(client, garmin_user, form_post, garmin_rows) -> None:
    link(form_post, client)
    r = link(form_post, client, alias="Otra")
    assert r.status_code == 422
    assert "Ya tienes vinculada esta cuenta Garmin como «Principal»." in r.text
    assert len(garmin_rows()) == 1


def test_same_identity_other_user(
    client, make_client, make_user, login_as, accept_notice, garmin_user, form_post, garmin_rows
) -> None:
    link(form_post, client)
    bea = make_user(display_name="Bea Secreta", email="bea.secreta@club.test")
    accept_notice(bea.user_id)
    other = make_client()
    login_as(other, bea)
    r = link(form_post, other, alias="La mía")
    assert r.status_code == 422
    assert "Esta cuenta Garmin ya está vinculada a otro usuario de garmin-hub." in r.text
    for leak in (garmin_user.display_name, garmin_user.email, "Principal"):
        assert leak not in r.text
    assert garmin_rows(bea.user_id) == []


def test_alias_taken_case_insensitive(client, garmin_user, form_post, garmin_rows) -> None:
    link(form_post, client, alias="Principal")
    r = link(form_post, client, alias="PRINCIPAL", email="ok+2@example.test")
    assert r.status_code == 422
    assert "Ya tienes una cuenta Garmin con ese alias." in r.text
    assert len(garmin_rows()) == 1


def test_max_accounts(client, garmin_user, form_post, make_garmin_account, fake_garmin) -> None:
    for _ in range(10):
        make_garmin_account(garmin_user.user_id)
    make_garmin_account(garmin_user.user_id, status="unlinked")
    assert client.get(LINK).status_code == 409
    r = link(form_post, client, email="ok+77@example.test")
    assert r.status_code == 409
    assert "Has alcanzado el máximo de 10 cuentas Garmin vinculadas." in r.text
    assert fake_garmin.calls == []


def test_unlinked_accounts_do_not_count(client, garmin_user, form_post, make_garmin_account):
    for _ in range(9):
        make_garmin_account(garmin_user.user_id)
    for _ in range(3):
        make_garmin_account(garmin_user.user_id, status="unlinked")
    assert link(form_post, client, email="ok+77@example.test").status_code == 303


def test_admin_gets_404(client, make_user, login_as, accept_notice, form_post) -> None:
    admin = make_user(role="admin")
    accept_notice(admin.user_id)
    login_as(client, admin)
    assert client.get(LINK).status_code == 404
    assert link(form_post, client).status_code == 404


def test_responses_never_echo_credentials(client, garmin_user, form_post) -> None:
    password = "contraseña-secreta-que-no-vuelve"
    for email in ("ok+1@example.test", "nadie@example.test", "mfa+3@example.test"):
        r = link(form_post, client, alias="Eco", email=email, password=password)
        assert password not in r.text
        assert email not in r.text
    r = link(form_post, client, alias="", email="ok+5@example.test", password=password)
    assert password not in r.text and "ok+5@example.test" not in r.text
