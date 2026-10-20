import json

import pytest

pytestmark = pytest.mark.integration


def test_export_includes_garmin_sections(
    client, garmin_user, make_garmin_account, make_user, accept_notice
) -> None:
    mine = make_garmin_account(garmin_user.user_id, alias="Principal", profile_id=987654)
    make_garmin_account(garmin_user.user_id, alias="Vieja", status="unlinked")
    other = make_user()
    make_garmin_account(other.user_id, alias="Ajena", profile_id=55555)
    r = client.get("/cuenta/exportar")
    assert r.status_code == 200
    data = r.json()
    accounts = data["garmin_accounts"]
    assert [a["alias"] for a in accounts] == ["Principal", "Vieja"]
    assert set(accounts[0]) == {
        "garmin_account_id",
        "alias",
        "status",
        "linked_at",
        "last_login_at",
        "last_sync_at",
        "last_checked_at",
        "unlinked_at",
    }
    assert accounts[0]["garmin_account_id"] == str(mine)
    assert accounts[1]["status"] == "unlinked" and accounts[1]["unlinked_at"]
    (acceptance,) = data["data_notice_acceptances"]
    assert set(acceptance) == {"notice_version", "accepted_at"}
    blob = json.dumps(data)
    for leak in ("ciphertext", "key_version", "garmin_profile_id", "987654", "Ajena", "@example"):
        assert leak not in blob
