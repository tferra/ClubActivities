import pytest
from sqlalchemy import select

from garmin_hub.accounts import deletion
from garmin_hub.db.schema import app_user

pytestmark = pytest.mark.integration


def test_failed_step_then_retry(
    client, make_client, csrf_for, make_user, login_as, engine, audit_rows, monkeypatch
) -> None:
    monkeypatch.setattr(deletion, "_STEPS", dict(deletion._STEPS))
    state = {"fail": True}

    def flaky(ctx, user_id):
        if state["fail"]:
            raise RuntimeError("disco no disponible")

    deletion.register_deletion_step("flaky", 500, flaky)
    user = make_user()
    login_as(client, user)
    r = client.post(
        "/cuenta/eliminar",
        data={
            "current_password": user.password,
            "confirmation": "ELIMINAR",
            "csrf_token": csrf_for(client),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    with engine.connect() as conn:
        status = conn.execute(
            select(app_user.c.status).where(app_user.c.user_id == user.user_id)
        ).scalar_one()
    assert status == "pending_deletion"
    assert audit_rows("user.deletion_step_failed")[0]["details"] == {"step": "flaky"}
    anon = make_client("192.0.2.80")
    login = anon.post(
        "/login",
        data={"email": user.email, "password": user.password, "csrf_token": csrf_for(anon)},
    )
    assert login.status_code == 422

    admin = make_user(role="admin")
    ac = make_client("192.0.2.81")
    login_as(ac, admin)
    assert "Borrado pendiente" in ac.get("/admin/usuarios").text
    state["fail"] = False
    r = ac.post(
        f"/admin/usuarios/{user.user_id}/reintentar-borrado",
        data={"csrf_token": csrf_for(ac)},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    with engine.connect() as conn:
        assert (
            conn.execute(select(app_user).where(app_user.c.user_id == user.user_id)).first() is None
        )
    assert audit_rows("user.deleted")[0]["details"]["by"] == "self"
    other = make_user()
    r = ac.post(
        f"/admin/usuarios/{other.user_id}/reintentar-borrado",
        data={"csrf_token": csrf_for(ac)},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 409
