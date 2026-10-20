import pytest

pytestmark = pytest.mark.integration

ATTENTION = "Estas cuentas necesitan atención"


def test_notice_lists_accounts_needing_attention(client, garmin_user, make_garmin_account):
    caducada = make_garmin_account(garmin_user.user_id, alias="Caducada", status="reauth_required")
    rota = make_garmin_account(garmin_user.user_id, alias="Rota", status="error")
    make_garmin_account(garmin_user.user_id, alias="Bien")
    text = client.get("/").text
    assert ATTENTION in text
    assert "«Caducada» (Requiere reautenticación)" in text
    assert "«Rota» (Error)" in text
    assert f'href="/cuentas-garmin/{caducada}/reautenticar"' in text
    assert f'href="/cuentas-garmin/{rota}/reautenticar"' in text
    assert "«Bien»" not in text


@pytest.mark.parametrize("status", ["valid", "unlinked", "deleting"])
def test_no_notice_for_other_statuses(client, garmin_user, make_garmin_account, status):
    make_garmin_account(garmin_user.user_id, status=status)
    assert ATTENTION not in client.get("/").text


def test_admin_sees_no_notice(client, make_user, login_as) -> None:
    admin = make_user(role="admin")
    login_as(client, admin)
    text = client.get("/").text
    assert ATTENTION not in text
    assert "versión nueva del aviso" not in text


NEW_VERSION = "Hay una versión nueva del aviso de datos"


def test_new_notice_version_with_linked_account(
    client, garmin_user, make_garmin_account, monkeypatch, garmin_rows
) -> None:
    from garmin_hub.garmin_accounts import notice

    make_garmin_account(garmin_user.user_id)
    assert NEW_VERSION not in client.get("/").text
    monkeypatch.setattr(notice, "NOTICE_VERSION", 2)
    text = client.get("/").text
    assert NEW_VERSION in text and 'href="/cuentas-garmin/aviso"' in text
    assert garmin_rows()[0]["status"] == "valid"  # no detiene nada


@pytest.mark.parametrize("status", [None, "unlinked"])
def test_no_new_version_notice_without_linked_accounts(
    client, garmin_user, make_garmin_account, monkeypatch, status
) -> None:
    from garmin_hub.garmin_accounts import notice

    if status:
        make_garmin_account(garmin_user.user_id, status=status)
    monkeypatch.setattr(notice, "NOTICE_VERSION", 2)
    assert NEW_VERSION not in client.get("/").text
