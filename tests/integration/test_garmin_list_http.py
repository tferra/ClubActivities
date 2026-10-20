import pytest
from sqlalchemy import update

from garmin_hub.db.schema import garmin_account

pytestmark = pytest.mark.integration

LIST = "/cuentas-garmin"


def test_two_accounts_with_dates(client, garmin_user, make_garmin_account, engine, clock) -> None:
    first = make_garmin_account(garmin_user.user_id, alias="Principal")
    clock.advance(minutes=1)
    make_garmin_account(garmin_user.user_id, alias="Bici")
    with engine.begin() as conn:
        conn.execute(
            update(garmin_account)
            .where(garmin_account.c.garmin_account_id == first)
            .values(last_checked_at=clock())
        )
    r = client.get(LIST)
    assert r.status_code == 200
    text = r.text
    assert text.index("Principal") < text.index("Bici")  # por fecha de creación
    assert text.count("Válida") >= 2
    assert "2026-10-19 12:00 UTC" in text  # último login
    assert "2026-10-19 12:01 UTC" in text  # última comprobación de Principal
    assert "Nunca" in text  # sincronización y comprobación sin valor
    assert f"/cuentas-garmin/{first}/comprobar" in text


def test_accounts_needing_attention(client, garmin_user, make_garmin_account) -> None:
    caducada = make_garmin_account(garmin_user.user_id, alias="Caducada", status="reauth_required")
    make_garmin_account(
        garmin_user.user_id, alias="Rota", status="error", error_code="token_undecryptable"
    )
    text = client.get(LIST).text
    assert "Requiere reautenticación" in text
    assert f'href="/cuentas-garmin/{caducada}/reautenticar" class="button primary"' in text
    assert "Error: No se puede usar el acceso guardado; vuelve a autenticar la cuenta." in text


def test_empty_list(client, garmin_user) -> None:
    r = client.get(LIST)
    assert "Todavía no has vinculado ninguna cuenta Garmin." in r.text
    assert 'href="/cuentas-garmin/vincular"' in r.text


def test_unlinked_and_deleting(client, garmin_user, make_garmin_account) -> None:
    kept = make_garmin_account(garmin_user.user_id, alias="Vieja", status="unlinked")
    stuck = make_garmin_account(garmin_user.user_id, alias="Atascada", status="deleting")
    text = client.get(LIST).text
    assert "Desvinculada (datos conservados)" in text
    assert f"/cuentas-garmin/{kept}/borrar-datos" in text
    assert "Borrando datos… (no se pudo completar)" in text
    assert f"/cuentas-garmin/{stuck}/reintentar-borrado" in text
    assert f"/cuentas-garmin/{kept}/comprobar" not in text
    assert f"/cuentas-garmin/{stuck}/desvincular" not in text


@pytest.mark.parametrize(
    ("flag", "message"),
    [
        ("vinculada", "Cuenta Garmin vinculada."),
        ("recuperada", "Se ha recuperado la cuenta con sus datos."),
        ("reautenticada", "Cuenta Garmin autenticada de nuevo."),
        ("desvinculada", "Cuenta Garmin desvinculada; sus datos se conservan."),
        ("borrada", "Se han borrado la cuenta Garmin y sus datos."),
    ],
)
def test_result_messages(client, garmin_user, flag, message) -> None:
    assert message in client.get(f"{LIST}?{flag}=1").text


def test_recovered_message_only_with_own_alias(
    client, garmin_user, make_garmin_account, make_user
) -> None:
    mine = make_garmin_account(garmin_user.user_id, alias="Bici")
    theirs = make_garmin_account(make_user().user_id, alias="Ajena")
    text = client.get(f"{LIST}?recuperada=1&cuenta={mine}").text
    assert "Se ha recuperado la cuenta «Bici» con sus datos." in text
    text = client.get(f"{LIST}?recuperada=1&cuenta={theirs}").text
    assert "Ajena" not in text and "Se ha recuperado la cuenta con sus datos." in text


def test_menu_link_only_for_regular_users(client, make_user, login_as) -> None:
    login_as(client, make_user())
    assert 'href="/cuentas-garmin"' in client.get("/").text
    login_as(client, make_user(role="admin"))
    assert 'href="/cuentas-garmin"' not in client.get("/").text
