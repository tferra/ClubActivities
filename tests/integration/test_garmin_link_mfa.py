import re

import pytest

from garmin_hub.garmin.fake import FAKE_MFA_CODE, FAKE_PASSWORD

pytestmark = pytest.mark.integration

ATTEMPT_RE = re.compile(r'name="attempt_id" value="([^"]+)"')


def start(form_post, client, email="mfa+2@example.test", alias="Bici"):
    r = form_post(
        client,
        "/cuentas-garmin/vincular",
        {"alias": alias, "garmin_email": email, "garmin_password": FAKE_PASSWORD},
    )
    assert r.status_code == 200, r.text
    return r, ATTEMPT_RE.search(r.text).group(1)


def send_code(form_post, client, attempt_id, code):
    return form_post(client, "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": code})


def test_mfa_page_then_wrong_then_right(
    client, garmin_user, form_post, garmin_rows, pending_logins
) -> None:
    r, attempt_id = start(form_post, client)
    assert 'name="mfa_code"' in r.text and "Cancelar" in r.text
    assert "5:00" in r.text  # tiempo restante
    r = send_code(form_post, client, attempt_id, "000000")
    assert r.status_code == 422
    assert "El código de verificación no es correcto." in r.text
    assert ATTEMPT_RE.search(r.text).group(1) == attempt_id
    r = send_code(form_post, client, attempt_id, FAKE_MFA_CODE)
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?vinculada=1"
    (row,) = garmin_rows(garmin_user.user_id)
    assert row["status"] == "valid" and row["alias"] == "Bici" and row["garmin_profile_id"] == 2
    assert pending_logins.get(attempt_id, garmin_user.user_id) is None


def test_expired_attempt(client, garmin_user, form_post, clock, garmin_rows) -> None:
    _, attempt_id = start(form_post, client)
    clock.advance(minutes=5, seconds=1)
    r = send_code(form_post, client, attempt_id, FAKE_MFA_CODE)
    assert r.status_code == 410
    assert "El intento ha caducado; vuelve a empezar." in r.text
    assert garmin_rows() == []


def test_cancel_discards_attempt(client, garmin_user, form_post, fake_garmin) -> None:
    _, attempt_id = start(form_post, client)
    r = form_post(client, "/cuentas-garmin/mfa/cancelar", {"attempt_id": attempt_id})
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin"
    assert ("discard",) in fake_garmin.calls
    assert send_code(form_post, client, attempt_id, FAKE_MFA_CODE).status_code == 410


def test_other_users_attempt_is_expired(
    client, garmin_user, form_post, make_client, make_user, login_as, accept_notice
) -> None:
    _, attempt_id = start(form_post, client)
    bea = make_user()
    accept_notice(bea.user_id)
    other = make_client()
    login_as(other, bea)
    r = send_code(form_post, other, attempt_id, FAKE_MFA_CODE)
    assert r.status_code == 410
    # sigue vivo para su dueño
    assert send_code(form_post, client, attempt_id, FAKE_MFA_CODE).status_code == 303


def test_new_attempt_discards_previous(client, garmin_user, form_post) -> None:
    _, first = start(form_post, client)
    _, second = start(form_post, client, email="mfa+3@example.test", alias="Otra")
    assert send_code(form_post, client, first, FAKE_MFA_CODE).status_code == 410
    assert send_code(form_post, client, second, FAKE_MFA_CODE).status_code == 303


def test_registry_full(client, garmin_user, form_post, pending_logins, monkeypatch) -> None:
    monkeypatch.setattr(pending_logins, "_max_entries", 0)
    r = form_post(
        client,
        "/cuentas-garmin/vincular",
        {"alias": "Bici", "garmin_email": "mfa+2@example.test", "garmin_password": FAKE_PASSWORD},
    )
    assert r.status_code == 422
    assert "no está disponible" in r.text


def test_mfa_code_never_echoed(client, garmin_user, form_post) -> None:
    _, attempt_id = start(form_post, client)
    r = send_code(form_post, client, attempt_id, "987123")
    assert "987123" not in r.text
