from datetime import timedelta

import pytest
from sqlalchemy import select, update

from garmin_hub.db.schema import garmin_account, garmin_token
from garmin_hub.garmin.client import MfaPending
from garmin_hub.garmin.fake import FAKE_PASSWORD
from garmin_hub.garmin_accounts import deletion

pytestmark = pytest.mark.integration


def unlink(form_post, client, account_id, mode="keep", confirmation="Principal"):
    data = {"confirmation": confirmation}
    if mode:
        data["mode"] = mode
    return form_post(client, f"/cuentas-garmin/{account_id}/desvincular", data)


def state(engine, account_id):
    with engine.connect() as conn:
        row = conn.execute(
            select(garmin_account).where(garmin_account.c.garmin_account_id == account_id)
        ).first()
        token = conn.execute(
            select(garmin_token).where(garmin_token.c.garmin_account_id == account_id)
        ).first()
    return row, token


def lock(engine, account_id, until):
    with engine.begin() as conn:
        conn.execute(
            update(garmin_account)
            .where(garmin_account.c.garmin_account_id == account_id)
            .values(request_lease_until=until)
        )


def test_confirmation_page(client, garmin_user, make_garmin_account) -> None:
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal")
    r = client.get(f"/cuentas-garmin/{account_id}/desvincular")
    assert r.status_code == 200
    assert "Conservar datos" in r.text and "Borrar datos" in r.text
    assert "los entrenadores a los que hayas dado consentimiento seguirán viéndolos" in r.text


@pytest.mark.parametrize(
    ("mode", "confirmation"), [(None, "Principal"), ("keep", "Otra"), ("delete", "")]
)
def test_validation(
    client, garmin_user, form_post, make_garmin_account, engine, mode, confirmation
):
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal")
    before = state(engine, account_id)
    r = unlink(form_post, client, account_id, mode, confirmation)
    assert r.status_code == 422
    assert state(engine, account_id) == before


def test_keep(
    client, garmin_user, form_post, make_garmin_account, engine, clock, app, fake_garmin
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal", profile_id=5)
    pending = MfaPending(handle=object())
    app.state.pending_logins.add(
        user_id=garmin_user.user_id,
        purpose="reauth",
        garmin_account_id=account_id,
        alias=None,
        pending=pending,
    )
    r = unlink(form_post, client, account_id, "keep", " principal ")
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?desvinculada=1"
    row, token = state(engine, account_id)
    assert row.status == "unlinked" and row.unlinked_at == clock() and token is None
    assert row.request_lease_until is None
    assert ("discard",) in fake_garmin.calls


def test_delete(client, garmin_user, form_post, make_garmin_account, engine) -> None:
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal")
    r = unlink(form_post, client, account_id, "delete")
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?borrada=1"
    assert state(engine, account_id) == (None, None)


@pytest.mark.parametrize("path", ["desvincular", "borrar-datos"])
def test_busy_lease(client, garmin_user, form_post, make_garmin_account, engine, clock, path):
    status = "valid" if path == "desvincular" else "unlinked"
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal", status=status)
    lock(engine, account_id, clock() + timedelta(seconds=30))
    before = state(engine, account_id)
    r = form_post(
        client,
        f"/cuentas-garmin/{account_id}/{path}",
        {"mode": "delete", "confirmation": "Principal"},
    )
    assert r.status_code == 409
    assert "Hay otra operación en curso con esta cuenta" in r.text
    assert state(engine, account_id) == before


def test_unlink_during_reauth_wins(
    client, garmin_user, form_post, make_garmin_account, engine, clock, app, fake_garmin, garmin_ctx
) -> None:
    """La desvinculación llega con el candado caducado mientras Garmin responde (R6, FR-021)."""
    account_id = make_garmin_account(
        garmin_user.user_id, alias="Principal", profile_id=7, status="reauth_required"
    )

    def unlink_meanwhile() -> None:
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

    fake_garmin.hooks["start_login"] = unlink_meanwhile
    r = form_post(
        client,
        f"/cuentas-garmin/{account_id}/reautenticar",
        {"garmin_email": "ok+7@example.test", "garmin_password": FAKE_PASSWORD},
    )
    assert r.status_code == 409
    assert "La cuenta ha cambiado mientras se comprobaba; recarga la página." in r.text
    row, token = state(engine, account_id)
    assert row.status == "unlinked" and token is None


def test_delete_data_later(client, garmin_user, form_post, make_garmin_account, engine) -> None:
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal", status="unlinked")
    r = client.get(f"/cuentas-garmin/{account_id}/borrar-datos")
    assert r.status_code == 200 and "Principal" in r.text
    r = form_post(
        client, f"/cuentas-garmin/{account_id}/borrar-datos", {"confirmation": "Principal"}
    )
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?borrada=1"
    assert state(engine, account_id) == (None, None)


def test_delete_data_requires_unlinked(client, garmin_user, form_post, make_garmin_account):
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal")
    assert client.get(f"/cuentas-garmin/{account_id}/borrar-datos").status_code == 409
    r = form_post(
        client, f"/cuentas-garmin/{account_id}/borrar-datos", {"confirmation": "Principal"}
    )
    assert r.status_code == 409


@pytest.mark.parametrize("status", ["unlinked", "deleting"])
def test_unlink_requires_linked(client, garmin_user, form_post, make_garmin_account, status):
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal", status=status)
    assert client.get(f"/cuentas-garmin/{account_id}/desvincular").status_code == 409
    assert unlink(form_post, client, account_id).status_code == 409


def test_audit(client, garmin_user, form_post, make_garmin_account, audit_rows) -> None:
    kept = make_garmin_account(garmin_user.user_id, alias="Principal")
    gone = make_garmin_account(garmin_user.user_id, alias="Bici")
    later = make_garmin_account(garmin_user.user_id, alias="Vieja", status="unlinked")
    unlink(form_post, client, kept, "keep")
    unlink(form_post, client, gone, "delete", "Bici")
    form_post(client, f"/cuentas-garmin/{later}/borrar-datos", {"confirmation": "Vieja"})
    assert [e["details"] for e in audit_rows("garmin.account_unlinked")] == [
        {"garmin_account_id": str(kept), "data": "kept"},
        {"garmin_account_id": str(gone), "data": "deleted"},
    ]
    assert [e["details"] for e in audit_rows("garmin.data_deletion_requested")] == [
        {"garmin_account_id": str(later)}
    ]
    deleted = [e["details"] for e in audit_rows("garmin.account_deleted")]
    assert [d["garmin_account_id"] for d in deleted] == [str(gone), str(later)]
    assert deleted[0]["steps"] == ["garmin_token", "garmin_account_row"]
