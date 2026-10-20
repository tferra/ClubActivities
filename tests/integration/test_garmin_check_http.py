import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from garmin_hub.db.schema import garmin_account, garmin_token
from garmin_hub.garmin.client import GarminUnavailable, RateLimited, VerifyResult
from garmin_hub.garmin_accounts import deletion
from garmin_hub.security.token_cipher import TokenCipher, parse_master_keys

pytestmark = pytest.mark.integration

HTMX = {"HX-Request": "true"}


def check(form_post, client, account_id):
    return form_post(client, f"/cuentas-garmin/{account_id}/comprobar", headers=HTMX)


def state(engine, account_id):
    with engine.connect() as conn:
        row = conn.execute(
            select(garmin_account).where(garmin_account.c.garmin_account_id == account_id)
        ).first()
        token = conn.execute(
            select(garmin_token).where(garmin_token.c.garmin_account_id == account_id)
        ).first()
    return row, token


def test_valid_access(
    client, garmin_user, form_post, make_garmin_account, engine, clock, audit_rows
):
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal", profile_id=1)
    r = check(form_post, client, account_id)
    assert r.status_code == 200
    assert r.text.lstrip().startswith(f'<tr id="garmin-{account_id}"')
    assert "Funciona correctamente." in r.text
    assert "2026-10-19 12:00 UTC" in r.text
    row, _ = state(engine, account_id)
    assert row.last_checked_at == clock() and row.request_lease_until is None
    (event,) = audit_rows("garmin.account_checked")
    assert event["details"] == {"garmin_account_id": str(account_id), "result": "ok"}


def test_rejected_access(client, garmin_user, form_post, make_garmin_account, engine, audit_rows):
    account_id = make_garmin_account(garmin_user.user_id, profile_id=9001)
    r = check(form_post, client, account_id)
    assert r.status_code == 200
    assert "Garmin ya no acepta el acceso guardado; vuelve a autenticar la cuenta." in r.text
    assert "Requiere reautenticación" in r.text
    assert state(engine, account_id)[0].status == "reauth_required"
    (changed,) = audit_rows("garmin.status_changed")
    assert changed["details"] == {
        "garmin_account_id": str(account_id),
        "from": "valid",
        "to": "reauth_required",
        "via": "check",
    }
    assert audit_rows("garmin.account_checked")[0]["details"]["result"] == "token_rejected"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (RateLimited, "Garmin está limitando las peticiones; inténtalo dentro de un rato."),
        (GarminUnavailable, "No se ha podido conectar con Garmin; inténtalo más tarde."),
    ],
)
def test_transient_errors_change_nothing(
    client,
    garmin_user,
    form_post,
    make_garmin_account,
    engine,
    fake_garmin,
    audit_rows,
    error,
    message,
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=3)
    fake_garmin.script_verify(3, error)
    r = check(form_post, client, account_id)
    assert r.status_code == 200 and message in r.text
    row, _ = state(engine, account_id)
    assert row.status == "valid" and row.last_checked_at is None
    assert audit_rows("garmin.account_checked")[0]["details"]["result"] == "transient"


def test_unlinked_while_checking(
    client, garmin_user, form_post, make_garmin_account, engine, fake_garmin, app, clock, garmin_ctx
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal", profile_id=3)

    def unlink_then_renew(tokens) -> VerifyResult:
        clock.advance(seconds=app.state.settings.garmin_request_lease_seconds + 1)
        deletion.unlink(
            garmin_ctx,
            user_id=garmin_user.user_id,
            account_id=account_id,
            mode="keep",
            confirmation="Principal",
            now=clock(),
            ip_prefix=None,
        )
        return fake_garmin._verify_outcome(3, tokens, "renew")

    fake_garmin.script_verify(3, unlink_then_renew)
    r = check(form_post, client, account_id)
    assert "La cuenta ha cambiado mientras se comprobaba; recarga la página." in r.text
    row, token = state(engine, account_id)
    assert row.status == "unlinked" and token is None


def test_once_per_minute(client, garmin_user, form_post, make_garmin_account, fake_garmin, clock):
    account_id = make_garmin_account(garmin_user.user_id, profile_id=3)
    assert check(form_post, client, account_id).status_code == 200
    calls = len(fake_garmin.calls)
    clock.advance(seconds=30)
    r = check(form_post, client, account_id)
    assert r.status_code == 409
    assert "Ya se ha comprobado hace menos de un minuto." in r.text
    assert len(fake_garmin.calls) == calls
    clock.advance(seconds=31)
    assert check(form_post, client, account_id).status_code == 200


def test_busy_lease(
    client, garmin_user, form_post, make_garmin_account, engine, clock, fake_garmin
):
    account_id = make_garmin_account(garmin_user.user_id, profile_id=3)
    with engine.begin() as conn:
        conn.execute(
            update(garmin_account)
            .where(garmin_account.c.garmin_account_id == account_id)
            .values(request_lease_until=clock() + timedelta(seconds=30))
        )
    r = check(form_post, client, account_id)
    assert r.status_code == 409 and "Hay otra operación en curso" in r.text
    assert fake_garmin.calls == []
    # el intento rechazado no consume la comprobación del minuto
    with engine.begin() as conn:
        conn.execute(update(garmin_account).values(request_lease_until=None))
    assert check(form_post, client, account_id).status_code == 200


def test_renewed_tokens_saved(
    client, garmin_user, form_post, make_garmin_account, engine, fake_garmin, app, clock
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=3)
    _, before = state(engine, account_id)
    clock.advance(minutes=1)
    fake_garmin.script_verify(3, "renew")
    check(form_post, client, account_id)
    _, after = state(engine, account_id)
    cipher = app.state.token_cipher
    assert json.loads(cipher.decrypt(after.ciphertext, after.key_version))["rev"] == 1
    assert after.updated_at == clock() and after.issued_at == before.issued_at
    assert after.key_version == cipher.current_version


def test_undecryptable_token(
    client, garmin_user, form_post, make_garmin_account, engine, fake_garmin, audit_rows, app
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=3)
    other = TokenCipher(parse_master_keys("3:" + "A" * 43 + "="))
    ciphertext, _ = other.encrypt(b"{}")
    with engine.begin() as conn:
        conn.execute(
            update(garmin_token)
            .where(garmin_token.c.garmin_account_id == account_id)
            .values(ciphertext=ciphertext, key_version=3)
        )
    r = check(form_post, client, account_id)
    assert "No se puede usar el acceso guardado; vuelve a autenticar la cuenta." in r.text
    row, _ = state(engine, account_id)
    assert (row.status, row.error_code) == ("error", "token_undecryptable")
    assert fake_garmin.calls == []
    (changed,) = audit_rows("garmin.status_changed")
    assert changed["details"]["via"] == "token_use"
    assert changed["details"]["error_code"] == "token_undecryptable"


def test_identity_mismatch(
    client, garmin_user, form_post, make_garmin_account, engine, fake_garmin
):
    account_id = make_garmin_account(garmin_user.user_id, profile_id=3)
    fake_garmin.script_verify(3, 4)
    r = check(form_post, client, account_id)
    assert "El acceso guardado corresponde a otra cuenta Garmin; vuelve a autenticarla." in r.text
    row, _ = state(engine, account_id)
    assert (row.status, row.error_code) == ("error", "identity_mismatch")


@pytest.mark.parametrize("status", ["unlinked", "deleting"])
def test_not_allowed_states(client, garmin_user, form_post, make_garmin_account, status):
    account_id = make_garmin_account(garmin_user.user_id, status=status)
    assert check(form_post, client, account_id).status_code == 409


def test_other_accounts_untouched(client, garmin_user, form_post, make_garmin_account, engine):
    target = make_garmin_account(garmin_user.user_id, profile_id=9001)
    other = make_garmin_account(garmin_user.user_id, profile_id=3)
    before = state(engine, other)
    check(form_post, client, target)
    assert state(engine, other) == before


def test_check_button_in_row(client, garmin_user, make_garmin_account) -> None:
    account_id = make_garmin_account(garmin_user.user_id)
    text = client.get("/cuentas-garmin").text
    assert f'hx-post="/cuentas-garmin/{account_id}/comprobar"' in text
