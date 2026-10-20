import pytest
from sqlalchemy import select

from garmin_hub.db.schema import garmin_account, garmin_token
from garmin_hub.garmin_accounts import deletion

pytestmark = pytest.mark.integration


@pytest.fixture
def flaky_step(monkeypatch):
    monkeypatch.setattr(deletion, "_STEPS", dict(deletion._STEPS))
    state = {"fail": True, "runs": 0}

    def flaky(ctx, account_id) -> None:
        state["runs"] += 1
        if state["fail"]:
            raise RuntimeError("fallo simulado")

    deletion.register_account_deletion_step("flaky", 500, flaky)
    return state


def test_failed_step_then_retry(
    client, garmin_user, form_post, make_garmin_account, engine, clock, audit_rows, flaky_step
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal")
    r = form_post(
        client,
        f"/cuentas-garmin/{account_id}/desvincular",
        {"mode": "delete", "confirmation": "Principal"},
    )
    assert r.status_code == 500
    assert "No se ha podido completar el borrado; inténtalo de nuevo." in r.text
    with engine.connect() as conn:
        row = conn.execute(
            select(garmin_account).where(garmin_account.c.garmin_account_id == account_id)
        ).one()
        assert conn.execute(select(garmin_token)).first() is None
    assert row.status == "deleting" and row.deletion_requested_at == clock()
    (failed,) = audit_rows("garmin.account_deletion_step_failed")
    assert failed["details"] == {"garmin_account_id": str(account_id), "step": "flaky"}
    assert failed["actor_user_id"] is None
    text = client.get("/cuentas-garmin").text
    assert f"/cuentas-garmin/{account_id}/reintentar-borrado" in text

    flaky_step["fail"] = False
    r = form_post(client, f"/cuentas-garmin/{account_id}/reintentar-borrado")
    assert r.status_code == 303 and r.headers["location"] == "/cuentas-garmin?borrada=1"
    with engine.connect() as conn:
        assert conn.execute(select(garmin_account)).first() is None
        assert conn.execute(select(garmin_token)).first() is None
    (deleted,) = audit_rows("garmin.account_deleted")
    assert deleted["details"]["steps"] == ["garmin_token", "flaky", "garmin_account_row"]


def test_retry_failing_again_keeps_deleting(
    client, garmin_user, form_post, make_garmin_account, garmin_rows, flaky_step
) -> None:
    account_id = make_garmin_account(garmin_user.user_id, alias="Principal", status="deleting")
    r = form_post(client, f"/cuentas-garmin/{account_id}/reintentar-borrado")
    assert r.status_code == 500
    assert garmin_rows()[0]["status"] == "deleting"


@pytest.mark.parametrize("status", ["valid", "unlinked"])
def test_retry_requires_deleting(client, garmin_user, form_post, make_garmin_account, status):
    account_id = make_garmin_account(garmin_user.user_id, status=status)
    assert form_post(client, f"/cuentas-garmin/{account_id}/reintentar-borrado").status_code == 409


def test_steps_are_idempotent(engine, clock, make_user, make_garmin_account) -> None:
    user = make_user()
    account_id = make_garmin_account(user.user_id)
    ctx = deletion.AccountDeletionContext(engine=engine, now=clock())
    for _ in range(2):
        for step in deletion.registered_account_steps():
            step.fn(ctx, account_id)
    with engine.connect() as conn:
        assert conn.execute(select(garmin_account)).first() is None


def test_row_step_is_last() -> None:
    steps = deletion.registered_account_steps()
    assert steps[-1].name == "garmin_account_row"
    assert steps[0].name == "garmin_token"
