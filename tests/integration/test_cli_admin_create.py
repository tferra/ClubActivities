import os
import secrets

import pytest
from sqlalchemy import insert, select
from typer.testing import CliRunner

from garmin_hub.cli.main import app
from garmin_hub.db.schema import app_user, invitation

pytestmark = [pytest.mark.integration, pytest.mark.mssql]

PASSWORD = "cielo-tranquilo-sobre-el-mar"


@pytest.fixture
def cli_env(tmp_path, monkeypatch, db_schema, raw_engine):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GARMIN_HUB_DB_URL", os.environ["GARMIN_HUB_TEST_DB_URL"])
    monkeypatch.setenv("GARMIN_HUB_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("GARMIN_HUB_PUBLIC_URL", "http://localhost:8000")
    monkeypatch.setenv("GARMIN_HUB_DB_SCHEMA", db_schema)


def create(email="admin@club.test", password=PASSWORD, confirm=None):
    confirm = password if confirm is None else confirm
    return CliRunner().invoke(
        app,
        ["admin", "create", "--email", email, "--name", "Admin"],
        input=f"{password}\n{confirm}\n",
    )


def test_admin_create_ok(cli_env, engine, audit_rows) -> None:
    result = create()
    assert result.exit_code == 0, result.output
    assert result.stdout.strip().splitlines()[-1].startswith("Administrador creado: ")
    assert "admin@club.test" not in result.output
    assert PASSWORD not in result.output
    with engine.connect() as conn:
        row = conn.execute(select(app_user)).one()
    assert (row.role, row.status, row.email) == ("admin", "active", "admin@club.test")
    events = audit_rows("admin.created")
    assert len(events) == 1
    assert events[0]["details"] == {"via": "cli"}
    assert events[0]["actor_user_id"] is None
    assert events[0]["ip_prefix"] is None


def test_duplicate_email(cli_env, engine, make_user) -> None:
    make_user(email="admin@club.test")
    result = create()
    assert result.exit_code == 1
    assert "Ya existe un usuario con ese correo." in result.output


def test_pending_invitation_email(cli_env, engine, clock) -> None:
    from datetime import timedelta
    from uuid import uuid4

    with engine.begin() as conn:
        conn.execute(
            insert(invitation).values(
                invitation_id=uuid4(),
                code_hash=secrets.token_bytes(32),
                email="admin@club.test",
                status="pending",
                created_at=clock(),
                expires_at=clock() + timedelta(days=7),
            )
        )
    result = create()
    assert result.exit_code == 1
    with engine.connect() as conn:
        assert conn.execute(select(app_user)).first() is None


def test_bad_password(cli_env, engine) -> None:
    result = create(password="corta")
    assert result.exit_code == 1
    assert "La contraseña debe tener al menos 12 caracteres." in result.output
    with engine.connect() as conn:
        assert conn.execute(select(app_user)).first() is None


def test_confirmation_mismatch(cli_env, engine) -> None:
    result = create(confirm="otra-cosa-distinta-larga")
    assert result.exit_code != 0
    with engine.connect() as conn:
        assert conn.execute(select(app_user)).first() is None


def test_schema_not_at_head(cli_env, monkeypatch) -> None:
    empty = f"gh_e_{secrets.token_hex(4)}"
    monkeypatch.setenv("GARMIN_HUB_DB_SCHEMA", empty)
    result = create()
    assert result.exit_code == 3
    assert "garmin-hub db upgrade" in result.output
