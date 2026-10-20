import os

from cryptography.fernet import Fernet
from typer.testing import CliRunner

from garmin_hub.cli.main import app


def test_key_generate_prints_valid_key_without_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # sin .env
    assert not [k for k in os.environ if k.startswith("GARMIN_HUB_") and "TEST" not in k]
    result = CliRunner().invoke(app, ["key", "generate"])
    assert result.exit_code == 0
    key, help_line = result.stdout.splitlines()
    Fernet(key.encode())  # clave válida
    assert help_line == (
        f"Añádela a GARMIN_HUB_MASTER_KEYS con una versión mayor que la actual, por ejemplo 2:{key}"
    )


def test_each_call_generates_a_new_key() -> None:
    first = CliRunner().invoke(app, ["key", "generate"]).stdout.splitlines()[0]
    second = CliRunner().invoke(app, ["key", "generate"]).stdout.splitlines()[0]
    assert first != second
