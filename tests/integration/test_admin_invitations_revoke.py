import pytest
from sqlalchemy import select

from garmin_hub.db.schema import invitation

pytestmark = pytest.mark.integration


@pytest.fixture
def admin_client(client, make_user, login_as):
    login_as(client, make_user(role="admin"))
    return client


def inv_id(engine, email):
    with engine.connect() as conn:
        return conn.execute(
            select(invitation.c.invitation_id).where(invitation.c.email == email)
        ).scalar_one()


def revoke(client, csrf_for, invitation_id):
    return client.post(
        f"/admin/invitaciones/{invitation_id}/revocar",
        data={"csrf_token": csrf_for(client)},
        headers={"HX-Request": "true"},
    )


def test_revoke_pending(
    admin_client, csrf_for, make_invitation, make_client, engine, audit_rows
) -> None:
    code = make_invitation("ana@club.test")
    r = revoke(admin_client, csrf_for, inv_id(engine, "ana@club.test"))
    assert r.status_code == 200 and "Revocada" in r.text
    assert audit_rows("invitation.revoked")
    anon = make_client("192.0.2.30")
    r = anon.post("/alta/codigo", data={"code": code, "csrf_token": csrf_for(anon)})
    assert r.status_code == 422 and "El código no es válido o ha caducado." in r.text


def test_revoke_used_conflict(admin_client, csrf_for, make_invitation, engine) -> None:
    make_invitation("usada@club.test", status="used")
    assert revoke(admin_client, csrf_for, inv_id(engine, "usada@club.test")).status_code == 409


def test_list_shows_expired_and_user(
    client, csrf_for, make_invitation, make_client, clock, make_user, login_as
) -> None:
    make_invitation("caduca@club.test", ttl_days=1)
    code = make_invitation("bea@club.test")
    anon = make_client("192.0.2.31")
    anon.post(
        "/alta",
        data={
            "code": code,
            "display_name": "Bea Usuaria",
            "password": "luna-llena-sobre-el-puerto",
            "password_confirm": "luna-llena-sobre-el-puerto",
            "csrf_token": csrf_for(anon),
        },
    )
    clock.advance(days=2)
    login_as(client, make_user(role="admin"))  # la sesión anterior habría caducado
    page = client.get("/admin/invitaciones").text
    assert "Caducada" in page
    assert "Usada" in page and "Bea Usuaria" in page
