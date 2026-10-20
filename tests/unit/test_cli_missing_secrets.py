import pytest
from typer.testing import CliRunner

from garmin_hub.cli.main import app

COMMANDS = [
    ["admin", "create", "--email", "a@club.test", "--name", "Ana"],
    ["db", "upgrade"],
    ["web", "serve"],
]
SECRETS_MESSAGE = (
    "Error: faltan secretos obligatorios: GARMIN_HUB_DB_URL, GARMIN_HUB_SESSION_SECRET.\n"
    "Defínelos como variables de entorno (ver .env.example).\n"
)


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # sin .env


@pytest.mark.parametrize("args", COMMANDS)
def test_missing_secrets_exit_2(args, monkeypatch) -> None:
    monkeypatch.setenv("GARMIN_HUB_PUBLIC_URL", "http://localhost:8000")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert result.stderr == SECRETS_MESSAGE


@pytest.mark.parametrize("args", COMMANDS)
def test_missing_public_url_exit_2(args, monkeypatch) -> None:
    monkeypatch.setenv("GARMIN_HUB_DB_URL", "mssql+pyodbc://u:topsecret@h/db")
    monkeypatch.setenv("GARMIN_HUB_SESSION_SECRET", "x" * 40)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert result.stderr == "Error: falta configuración obligatoria: GARMIN_HUB_PUBLIC_URL.\n"
    assert "topsecret" not in result.output


def test_admin_create_has_no_password_option() -> None:
    result = CliRunner().invoke(app, ["admin", "create", "--help"])
    assert result.exit_code == 0
    assert "--password" not in result.output
