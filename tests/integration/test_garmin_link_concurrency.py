import threading

import pytest

from garmin_hub.garmin.fake import FAKE_PASSWORD

pytestmark = [pytest.mark.integration, pytest.mark.mssql]


def test_two_users_link_same_identity_at_once(
    make_client, make_user, login_as, accept_notice, form_post, garmin_rows, fake_garmin
) -> None:
    clients = []
    for _ in range(2):
        user = make_user()
        accept_notice(user.user_id)
        client = make_client()
        login_as(client, user)
        clients.append(client)
    barrier = threading.Barrier(2)
    fake_garmin.hooks["start_login"] = lambda: None
    results: list[int] = []
    texts: list[str] = []

    def run(client) -> None:
        barrier.wait()
        r = form_post(
            client,
            "/cuentas-garmin/vincular",
            {
                "alias": "Misma",
                "garmin_email": "ok+500@example.test",
                "garmin_password": FAKE_PASSWORD,
            },
        )
        results.append(r.status_code)
        texts.append(r.text)

    threads = [threading.Thread(target=run, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [303, 422]
    assert any("ya está vinculada a otro usuario" in t for t in texts)
    assert [r["status"] for r in garmin_rows()] == ["valid"]
