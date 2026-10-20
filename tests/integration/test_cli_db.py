import os

import pytest
from typer.testing import CliRunner

from garmin_hub.cli.main import app
from garmin_hub.db.migrate import head_revision

pytestmark = [pytest.mark.integration, pytest.mark.mssql]


@pytest.fixture
def cli_env(tmp_path, monkeypatch, db_schema, raw_engine):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GARMIN_HUB_DB_URL", os.environ["GARMIN_HUB_TEST_DB_URL"])
    monkeypatch.setenv("GARMIN_HUB_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("GARMIN_HUB_PUBLIC_URL", "http://localhost:8000")
    monkeypatch.setenv("GARMIN_HUB_DB_SCHEMA", db_schema)


def test_db_upgrade_twice(cli_env) -> None:
    runner = CliRunner()
    for _ in range(2):
        result = runner.invoke(app, ["db", "upgrade"])
        assert result.exit_code == 0, result.output
        assert result.stdout == f"Base de datos actualizada a la revisión {head_revision()}.\n"
