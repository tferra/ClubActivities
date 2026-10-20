import pytest
from sqlalchemy import select

from garmin_hub.db.schema import data_notice_acceptance
from garmin_hub.garmin.fake import FAKE_PASSWORD
from garmin_hub.garmin_accounts import notice

pytestmark = pytest.mark.integration

LINK_FORM = {"alias": "Mía", "garmin_email": "ok+1@example.test", "garmin_password": FAKE_PASSWORD}


@pytest.fixture
def user_without_notice(client, make_user, login_as):
    user = make_user()
    login_as(client, user)
    return user


def acceptances(engine, user_id):
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(data_notice_acceptance).where(data_notice_acceptance.c.user_id == user_id)
            )
        )


def test_link_redirects_to_notice(client, user_without_notice, form_post, fake_garmin) -> None:
    target = "/cuentas-garmin/aviso?next=/cuentas-garmin/vincular"
    r = client.get("/cuentas-garmin/vincular", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == target
    r = form_post(client, "/cuentas-garmin/vincular", LINK_FORM)
    assert r.status_code == 303 and r.headers["location"] == target
    assert fake_garmin.calls == []


def test_accept_requires_checkbox(client, user_without_notice, form_post, engine) -> None:
    r = form_post(client, "/cuentas-garmin/aviso", {"next": "/cuentas-garmin/vincular"})
    assert r.status_code == 422
    assert acceptances(engine, user_without_notice.user_id) == []


def test_accept_and_redirect(
    client, user_without_notice, form_post, engine, audit_rows, clock
) -> None:
    r = form_post(
        client, "/cuentas-garmin/aviso", {"accept": "1", "next": "/cuentas-garmin/vincular"}
    )
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin/vincular"
    (row,) = acceptances(engine, user_without_notice.user_id)
    assert row.notice_version == notice.NOTICE_VERSION and row.accepted_at == clock()
    (event,) = audit_rows("garmin.notice_accepted")
    assert event["details"] == {"notice_version": notice.NOTICE_VERSION}
    # repetir no duplica ni audita de nuevo
    form_post(client, "/cuentas-garmin/aviso", {"accept": "1", "next": "/cuentas-garmin"})
    assert len(acceptances(engine, user_without_notice.user_id)) == 1
    assert len(audit_rows("garmin.notice_accepted")) == 1
    assert client.get("/cuentas-garmin/vincular").status_code == 200


@pytest.mark.parametrize(
    "next_url",
    ["https://evil.test", "//evil.test", "/cuenta", "/cuentas-garminx", "", "/cuentas-garmin/\\x"],
)
def test_unsafe_next_falls_back(client, user_without_notice, form_post, next_url) -> None:
    r = form_post(client, "/cuentas-garmin/aviso", {"accept": "1", "next": next_url})
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin"


def test_new_version_asks_again(
    client, garmin_user, form_post, make_garmin_account, monkeypatch, fake_garmin
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, profile_id=7)
    monkeypatch.setattr(notice, "NOTICE_VERSION", 2)
    r = form_post(client, "/cuentas-garmin/vincular", LINK_FORM)
    assert r.headers["location"] == "/cuentas-garmin/aviso?next=/cuentas-garmin/vincular"
    reauth = f"/cuentas-garmin/{account_id}/reautenticar"
    r = client.get(reauth, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/cuentas-garmin/aviso?next={reauth}"
    r = form_post(
        client, reauth, {"garmin_email": "ok+7@example.test", "garmin_password": FAKE_PASSWORD}
    )
    assert r.status_code == 303 and r.headers["location"] == f"/cuentas-garmin/aviso?next={reauth}"
    assert fake_garmin.calls == []


def test_notice_content(client, user_without_notice) -> None:
    r = client.get("/cuentas-garmin/aviso?next=/cuentas-garmin/vincular")
    assert r.status_code == 200
    text = r.text
    for phrase in (
        "actividades",
        "recorridos con GPS",
        "datos de salud",
        "solo tú y los entrenadores a los que des consentimiento",
        "El administrador de garmin-hub no puede verlos",
        "desvincular",
        "borrar",
        "He leído y acepto",
        'name="next" value="/cuentas-garmin/vincular"',
    ):
        assert phrase in text, phrase
