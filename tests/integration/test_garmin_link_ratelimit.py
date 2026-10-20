import re

import pytest

from garmin_hub.garmin.fake import FAKE_PASSWORD

pytestmark = pytest.mark.integration

THROTTLED = "Has hecho demasiados intentos con Garmin; espera unos minutos."


def link(form_post, client, email, password=FAKE_PASSWORD, alias="Principal"):
    return form_post(
        client,
        "/cuentas-garmin/vincular",
        {"alias": alias, "garmin_email": email, "garmin_password": password},
    )


def test_five_bad_credentials_block_the_sixth(client, garmin_user, form_post, fake_garmin):
    for _ in range(5):
        assert link(form_post, client, "ok+1@example.test", "mala").status_code == 422
    calls = len(fake_garmin.calls)
    r = link(form_post, client, "ok+1@example.test")
    assert r.status_code == 429 and THROTTLED in r.text
    assert len(fake_garmin.calls) == calls


def test_bad_mfa_codes_count(client, garmin_user, form_post, fake_garmin) -> None:
    r = link(form_post, client, "mfa+2@example.test")
    attempt_id = re.search(r'name="attempt_id" value="([^"]+)"', r.text).group(1)
    for _ in range(5):
        r = form_post(
            client, "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": "000000"}
        )
        assert r.status_code == 422
    calls = len(fake_garmin.calls)
    r = form_post(client, "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": "123456"})
    assert r.status_code == 429 and THROTTLED in r.text
    assert len(fake_garmin.calls) == calls


def test_transient_and_local_errors_do_not_count(
    client, garmin_user, form_post, make_garmin_account
) -> None:
    make_garmin_account(garmin_user.user_id, alias="Ocupado", profile_id=50)
    for _ in range(3):
        link(form_post, client, "down@example.test")
        link(form_post, client, "ratelimit@example.test")
        link(form_post, client, "blocked@example.test")
        link(form_post, client, "ok+60@example.test", alias="")  # alias no válido
        link(form_post, client, "ok+61@example.test", alias="ocupado")  # alias en uso
        link(form_post, client, "ok+50@example.test", alias="Dup")  # ya vinculada
    assert link(form_post, client, "ok+1@example.test").status_code == 303


def test_window_expires(client, garmin_user, form_post, clock) -> None:
    for _ in range(5):
        link(form_post, client, "ok+1@example.test", "mala")
    assert link(form_post, client, "ok+1@example.test").status_code == 429
    clock.advance(minutes=15, seconds=1)
    assert link(form_post, client, "ok+1@example.test").status_code == 303


def test_limit_is_per_user(
    client, garmin_user, form_post, make_client, make_user, login_as, accept_notice
) -> None:
    for _ in range(5):
        link(form_post, client, "ok+1@example.test", "mala")
    bea = make_user()
    accept_notice(bea.user_id)
    other = make_client()
    login_as(other, bea)
    assert link(form_post, other, "ok+1@example.test").status_code == 303
