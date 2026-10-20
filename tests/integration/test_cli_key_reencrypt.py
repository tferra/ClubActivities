import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from typer.testing import CliRunner

from garmin_hub.cli import main as cli
from garmin_hub.db.schema import garmin_token
from garmin_hub.garmin.client import GarminTokens
from garmin_hub.garmin_accounts.accounts import save_token
from garmin_hub.security.token_cipher import TokenCipher, parse_master_keys

pytestmark = pytest.mark.integration

K1, K2, K3 = (Fernet.generate_key().decode() for _ in range(3))


@pytest.fixture
def run(engine, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # sin .env
    monkeypatch.setattr(cli, "_engine_at_head", lambda runtime: engine)

    def invoke(master_keys: str):
        env = {
            "GARMIN_HUB_PUBLIC_URL": "http://localhost:8000",
            "GARMIN_HUB_DB_URL": "mssql+pyodbc://u:db-secret@h/db",
            "GARMIN_HUB_SESSION_SECRET": "x" * 40,
            "GARMIN_HUB_MASTER_KEYS": master_keys,
            "GARMIN_HUB_LOG_DIR": str(tmp_path / "logs"),
        }
        return CliRunner().invoke(cli.app, ["key", "reencrypt"], env=env)

    return invoke


def seed(engine, clock, make_user, make_garmin_account, version_key: str, count: int) -> list:
    user = make_user()
    cipher = TokenCipher(parse_master_keys(version_key))
    ids = []
    for n in range(count):
        account_id = make_garmin_account(user.user_id, with_token=False)
        value = json.dumps({"di_refresh_token": f"REFRESH-{n}"}).encode()
        with engine.begin() as conn:
            save_token(conn, account_id, GarminTokens(value), cipher, clock())
        ids.append(account_id)
    return ids


def tokens(engine):
    with engine.connect() as conn:
        return list(conn.execute(select(garmin_token)))


def test_reencrypt_to_current_version(run, engine, clock, make_user, make_garmin_account):
    seed(engine, clock, make_user, make_garmin_account, f"1:{K1}", 3)
    result = run(f"2:{K2},1:{K1}")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Accesos recifrados: 3. Pendientes con versiones no configuradas: 0.\n"
    cipher = TokenCipher(parse_master_keys(f"2:{K2}"))
    for row in tokens(engine):
        assert row.key_version == 2
        assert b"REFRESH-" in cipher.decrypt(row.ciphertext, 2)
    again = run(f"2:{K2},1:{K1}")
    assert again.exit_code == 0
    assert again.stdout.startswith("Accesos recifrados: 0.")


def test_unconfigured_version_is_pending(run, engine, clock, make_user, make_garmin_account):
    seed(engine, clock, make_user, make_garmin_account, f"1:{K1}", 1)
    seed(engine, clock, make_user, make_garmin_account, f"3:{K3}", 1)
    result = run(f"2:{K2},1:{K1}")
    assert result.exit_code == 1
    assert result.stdout == "Accesos recifrados: 1. Pendientes con versiones no configuradas: 1.\n"
    assert sorted(r.key_version for r in tokens(engine)) == [2, 3]
    for secret in (K1, K2, K3, "REFRESH-"):
        assert secret not in result.output
