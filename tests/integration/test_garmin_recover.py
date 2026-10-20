import pytest
from sqlalchemy import select

from garmin_hub.db.schema import garmin_token
from garmin_hub.garmin.fake import FAKE_PASSWORD

pytestmark = pytest.mark.integration


def link(form_post, client, alias, email):
    return form_post(
        client,
        "/cuentas-garmin/vincular",
        {"alias": alias, "garmin_email": email, "garmin_password": FAKE_PASSWORD},
    )


def unlink_keep(form_post, client, account_id, alias):
    r = form_post(
        client,
        f"/cuentas-garmin/{account_id}/desvincular",
        {"mode": "keep", "confirmation": alias},
    )
    assert r.status_code == 303


def test_recover_same_row(client, garmin_user, form_post, garmin_rows, engine, audit_rows):
    assert link(form_post, client, "Bici", "ok+5@example.test").status_code == 303
    (row,) = garmin_rows()
    unlink_keep(form_post, client, row["garmin_account_id"], "Bici")
    r = link(form_post, client, "Otro alias", "ok+5@example.test")
    assert r.status_code == 303
    assert r.headers["location"] == (
        f"/cuentas-garmin?recuperada=1&cuenta={row['garmin_account_id']}"
    )
    assert (
        "Se ha recuperado la cuenta «Bici» con sus datos." in client.get(r.headers["location"]).text
    )
    (again,) = garmin_rows()
    assert again["garmin_account_id"] == row["garmin_account_id"]
    assert again["alias"] == "Bici" and again["status"] == "valid"
    assert again["unlinked_at"] is None
    with engine.connect() as conn:
        assert conn.execute(select(garmin_token)).first() is not None
    linked = audit_rows("garmin.account_linked")
    assert [e["details"]["recovered"] for e in linked] == [False, True]


def test_other_user_gets_new_row(
    client, garmin_user, form_post, garmin_rows, make_client, make_user, login_as, accept_notice
) -> None:
    link(form_post, client, "Bici", "ok+5@example.test")
    (row,) = garmin_rows()
    unlink_keep(form_post, client, row["garmin_account_id"], "Bici")
    bea = make_user()
    accept_notice(bea.user_id)
    other = make_client()
    login_as(other, bea)
    assert link(form_post, other, "La de Bea", "ok+5@example.test").status_code == 303
    (bea_row,) = garmin_rows(bea.user_id)
    assert bea_row["garmin_account_id"] != row["garmin_account_id"]
    assert other.get(f"/cuentas-garmin/{row['garmin_account_id']}/borrar-datos").status_code == 404
    # A ya no puede recuperarla: está vinculada a otro usuario
    r = link(form_post, client, "Bici", "ok+5@example.test")
    assert r.status_code == 422
    assert "Esta cuenta Garmin ya está vinculada a otro usuario de garmin-hub." in r.text
    assert [r["status"] for r in garmin_rows(garmin_user.user_id)] == ["unlinked"]


def test_recovery_counts_for_limit(
    client, garmin_user, form_post, make_garmin_account, garmin_rows
) -> None:
    kept = make_garmin_account(garmin_user.user_id, alias="Vieja", profile_id=5, status="unlinked")
    for _ in range(10):
        make_garmin_account(garmin_user.user_id)
    r = link(form_post, client, "Vieja", "ok+5@example.test")
    assert r.status_code == 409
    statuses = {r["garmin_account_id"]: r["status"] for r in garmin_rows()}
    assert statuses[kept] == "unlinked"


def test_deleting_identity_can_be_linked_again(
    client, garmin_user, form_post, make_garmin_account, garmin_rows
) -> None:
    stuck = make_garmin_account(
        garmin_user.user_id, alias="Atascada", profile_id=5, status="deleting"
    )
    assert link(form_post, client, "Nueva", "ok+5@example.test").status_code == 303
    ids = {r["garmin_account_id"] for r in garmin_rows()}
    assert stuck in ids and len(ids) == 2
