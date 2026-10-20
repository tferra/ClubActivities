import json
import re
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from garmin_hub.db.schema import garmin_account, garmin_token
from garmin_hub.garmin.fake import FAKE_MFA_CODE, FAKE_PASSWORD

pytestmark = pytest.mark.integration


def reauth(form_post, client, account_id, email, password=FAKE_PASSWORD):
    return form_post(
        client,
        f"/cuentas-garmin/{account_id}/reautenticar",
        {"garmin_email": email, "garmin_password": password},
    )


def account(engine, account_id):
    with engine.connect() as conn:
        row = conn.execute(
            select(garmin_account).where(garmin_account.c.garmin_account_id == account_id)
        ).one()
        token = conn.execute(
            select(garmin_token).where(garmin_token.c.garmin_account_id == account_id)
        ).first()
    return row, token


def test_get_form(client, garmin_user, make_garmin_account) -> None:
    account_id = make_garmin_account(
        garmin_user.user_id, alias="Caducada", status="reauth_required"
    )
    r = client.get(f"/cuentas-garmin/{account_id}/reautenticar")
    assert r.status_code == 200
    assert "Caducada" in r.text
    assert "Introduce las credenciales de la misma cuenta Garmin" in r.text


def test_reauth_from_reauth_required(
    client, garmin_user, form_post, make_garmin_account, engine, clock, app
) -> None:
    account_id = make_garmin_account(
        garmin_user.user_id, alias="Caducada", profile_id=7, status="reauth_required"
    )
    _, old_token = account(engine, account_id)
    clock.advance(minutes=10)
    r = reauth(form_post, client, account_id, "ok+7@example.test")
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?reautenticada=1"
    row, token = account(engine, account_id)
    assert row.status == "valid" and row.alias == "Caducada"
    assert row.last_login_at == clock()
    assert token.issued_at == clock() and token.issued_at != old_token.issued_at
    assert (
        json.loads(app.state.token_cipher.decrypt(token.ciphertext, token.key_version))["rev"] == 1
    )
    assert row.request_lease_until is None


@pytest.mark.parametrize("status", ["error", "valid"])
def test_reauth_from_error_and_valid(
    client, garmin_user, form_post, make_garmin_account, engine, status
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7, status=status)
    assert reauth(form_post, client, account_id, "ok+7@example.test").status_code == 303
    row, _ = account(engine, account_id)
    assert row.status == "valid" and row.error_code is None


def test_reauth_with_mfa(client, garmin_user, form_post, make_garmin_account, engine) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7, status="reauth_required")
    r = reauth(form_post, client, account_id, "mfa+7@example.test")
    assert r.status_code == 200 and "volver a autenticar la cuenta" in r.text
    attempt_id = re.search(r'name="attempt_id" value="([^"]+)"', r.text).group(1)
    r = form_post(
        client, "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": FAKE_MFA_CODE}
    )
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?reautenticada=1"
    assert account(engine, account_id)[0].status == "valid"


def test_other_identity_rejected(
    client, garmin_user, form_post, make_garmin_account, engine, fake_garmin
) -> None:
    account_id = make_garmin_account(
        garmin_user.user_id, alias="Caducada", profile_id=7, status="reauth_required"
    )
    before = account(engine, account_id)
    for _ in range(6):  # no cuenta para el límite de intentos
        r = reauth(form_post, client, account_id, "ok+8@example.test")
        assert r.status_code == 422
    assert "Esas credenciales son de otra cuenta Garmin distinta de «Caducada»." in r.text
    after = account(engine, account_id)
    assert after[0].status == before[0].status
    assert after[1] == before[1]
    assert reauth(form_post, client, account_id, "ok+7@example.test").status_code == 303


def test_other_accounts_untouched(
    client, garmin_user, form_post, make_garmin_account, engine
) -> None:
    target = make_garmin_account(garmin_user.user_id, profile_id=7, status="reauth_required")
    other = make_garmin_account(garmin_user.user_id, profile_id=9, status="reauth_required")
    before = account(engine, other)
    reauth(form_post, client, target, "ok+7@example.test")
    assert account(engine, other) == before


@pytest.mark.parametrize("status", ["unlinked", "deleting"])
def test_not_allowed_states(client, garmin_user, form_post, make_garmin_account, status):
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7, status=status)
    assert client.get(f"/cuentas-garmin/{account_id}/reautenticar").status_code == 409
    r = reauth(form_post, client, account_id, "ok+7@example.test")
    assert r.status_code == 409


def test_busy_lease(
    client, garmin_user, form_post, make_garmin_account, engine, clock, fake_garmin
):
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7, status="reauth_required")
    with engine.begin() as conn:
        conn.execute(
            update(garmin_account)
            .where(garmin_account.c.garmin_account_id == account_id)
            .values(request_lease_until=clock() + timedelta(seconds=30))
        )
    r = reauth(form_post, client, account_id, "ok+7@example.test")
    assert r.status_code == 409
    assert "Hay otra operación en curso con esta cuenta; inténtalo en unos segundos." in r.text
    assert fake_garmin.calls == []


def test_lease_released_after_failure(
    client, garmin_user, form_post, make_garmin_account, engine
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7, status="reauth_required")
    reauth(form_post, client, account_id, "down@example.test")
    assert account(engine, account_id)[0].request_lease_until is None
    assert reauth(form_post, client, account_id, "ok+7@example.test").status_code == 303


def test_throttle_applies(client, garmin_user, form_post, make_garmin_account, fake_garmin):
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7, status="reauth_required")
    for _ in range(5):
        reauth(form_post, client, account_id, "ok+7@example.test", "mala")
    calls = len(fake_garmin.calls)
    r = reauth(form_post, client, account_id, "ok+7@example.test")
    assert r.status_code == 429
    assert len(fake_garmin.calls) == calls


def test_audit(client, garmin_user, form_post, make_garmin_account, audit_rows) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7, status="reauth_required")
    reauth(form_post, client, account_id, "ok+7@example.test", "mala")
    reauth(form_post, client, account_id, "ok+8@example.test")
    reauth(form_post, client, account_id, "ok+7@example.test")
    failed = [e["details"] for e in audit_rows("garmin.reauth_failed")]
    assert failed == [
        {"garmin_account_id": str(account_id), "reason": "bad_credentials"},
        {"garmin_account_id": str(account_id), "reason": "identity_mismatch"},
    ]
    (done,) = audit_rows("garmin.reauthenticated")
    assert done["details"] == {"garmin_account_id": str(account_id), "mfa": False}
