from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from garmin_hub.config import MissingConfigError, Settings, load_env_file, load_settings
from garmin_hub.secrets import EnvSecretProvider, MissingSecretsError, load_secrets

GOOD_SECRET = "s" * 40
GOOD_KEYS = f"1:{Fernet.generate_key().decode()}"
BASE = {
    "GARMIN_HUB_DB_URL": "x",
    "GARMIN_HUB_SESSION_SECRET": GOOD_SECRET,
    "GARMIN_HUB_MASTER_KEYS": GOOD_KEYS,
}


class FakeProvider:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, name: str) -> str | None:
        return self.values.get(name)


def test_missing_secrets_names_without_values() -> None:
    with pytest.raises(MissingSecretsError) as exc:
        load_secrets(FakeProvider({}))
    message = exc.value.message
    assert message == (
        "faltan secretos obligatorios: GARMIN_HUB_DB_URL, GARMIN_HUB_SESSION_SECRET, "
        "GARMIN_HUB_MASTER_KEYS."
    )


def test_missing_one_secret_does_not_leak_the_other_value() -> None:
    with pytest.raises(MissingSecretsError) as exc:
        load_secrets(FakeProvider({"GARMIN_HUB_DB_URL": "mssql://u:supersecret@h/db"}))
    assert "GARMIN_HUB_SESSION_SECRET" in exc.value.message
    assert "supersecret" not in exc.value.message


def test_short_session_secret_is_rejected() -> None:
    with pytest.raises(MissingSecretsError) as exc:
        load_secrets(FakeProvider({**BASE, "GARMIN_HUB_SESSION_SECRET": "short"}))
    assert exc.value.invalid == ["GARMIN_HUB_SESSION_SECRET"]
    assert "short" not in exc.value.message


def test_load_secrets_ok() -> None:
    secrets = load_secrets(FakeProvider(BASE))
    assert secrets.session_secret == GOOD_SECRET.encode()
    assert secrets.master_keys == GOOD_KEYS
    assert GOOD_SECRET not in repr(secrets)
    assert GOOD_KEYS not in repr(secrets)


def test_missing_master_keys_is_named() -> None:
    values = {k: v for k, v in BASE.items() if k != "GARMIN_HUB_MASTER_KEYS"}
    with pytest.raises(MissingSecretsError) as exc:
        load_secrets(FakeProvider(values))
    assert exc.value.missing == ["GARMIN_HUB_MASTER_KEYS"]
    assert exc.value.message == "faltan secretos obligatorios: GARMIN_HUB_MASTER_KEYS."


KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


@pytest.mark.parametrize(
    "raw",
    [
        KEY_A,  # sin versión
        f"uno:{KEY_A}",  # versión no entera
        f"0:{KEY_A}",  # versión no positiva
        f"1:{KEY_A},1:{KEY_B}",  # versión repetida
        "1:clave-que-no-es-fernet",
        f"1:{KEY_A};2:{KEY_B}",  # separador incorrecto
    ],
)
def test_invalid_master_keys_listed_without_values(raw: str) -> None:
    with pytest.raises(MissingSecretsError) as exc:
        load_secrets(FakeProvider({**BASE, "GARMIN_HUB_MASTER_KEYS": raw}))
    assert exc.value.missing == []
    assert exc.value.invalid == ["GARMIN_HUB_MASTER_KEYS"]
    assert exc.value.message == (
        "secretos no válidos: GARMIN_HUB_MASTER_KEYS (formato "
        "<versión>:<clave>[,<versión>:<clave>...] con claves Fernet)."
    )
    assert KEY_A not in exc.value.message and KEY_B not in exc.value.message


def test_settings_garmin_defaults() -> None:
    s = load_settings({}, environ={"GARMIN_HUB_PUBLIC_URL": "https://hub.example"})
    assert s.garmin_client == "garminconnect"
    assert s.garmin_mfa_ttl_minutes == 5
    assert s.garmin_max_accounts == 10
    assert (s.garmin_login_max_failures, s.garmin_login_window_minutes) == (5, 15)
    assert s.garmin_check_interval_seconds == 60
    assert s.garmin_request_lease_seconds == 120
    assert s.garmin_max_retries == 2
    assert s.garmin_login_max_retries == 0
    assert s.garmin_login_strategy_pause_seconds == 2
    assert s.garmin_login_budget_seconds == 45


def test_settings_garmin_from_env() -> None:
    s = load_settings(
        {},
        environ={
            "GARMIN_HUB_PUBLIC_URL": "https://hub.example",
            "GARMIN_HUB_GARMIN_MAX_ACCOUNTS": "3",
            "GARMIN_HUB_GARMIN_LOGIN_BUDGET_SECONDS": "30",
        },
    )
    assert s.garmin_max_accounts == 3
    assert s.garmin_login_budget_seconds == 30


def test_fake_garmin_client_rejected_in_prod() -> None:
    with pytest.raises(MissingConfigError) as exc:
        load_settings(
            {},
            environ={
                "GARMIN_HUB_PUBLIC_URL": "https://hub.example",
                "GARMIN_HUB_ENV": "prod",
                "GARMIN_HUB_GARMIN_CLIENT": "fake",
            },
        )
    assert exc.value.names == ["GARMIN_HUB_GARMIN_CLIENT"]
    assert exc.value.message == (
        "falta configuración obligatoria: GARMIN_HUB_GARMIN_CLIENT (fake solo en dev o test)."
    )


@pytest.mark.parametrize("env", ["dev", "test"])
def test_fake_garmin_client_allowed_outside_prod(env: str) -> None:
    s = load_settings(
        {},
        environ={
            "GARMIN_HUB_PUBLIC_URL": "https://hub.example",
            "GARMIN_HUB_ENV": env,
            "GARMIN_HUB_GARMIN_CLIENT": "fake",
        },
    )
    assert s.garmin_client == "fake"


def test_settings_defaults_fr002() -> None:
    s = load_settings({}, environ={"GARMIN_HUB_PUBLIC_URL": "https://hub.example"})
    assert (s.invite_ttl_days, s.reset_ttl_hours) == (7, 24)
    assert (s.session_idle_minutes, s.session_max_hours) == (30, 12)
    assert (s.login_pair_max_failures, s.login_pair_window_minutes) == (5, 15)
    assert (s.login_ip_max_failures, s.login_ip_window_minutes) == (20, 15)
    assert s.login_email_soft_limit == 50
    assert s.login_email_soft_window_minutes == 60
    assert s.login_email_max_delay_seconds == 10
    assert s.db_schema == "gh"


def test_settings_override_from_env() -> None:
    s = load_settings(
        {},
        environ={"GARMIN_HUB_PUBLIC_URL": "https://hub.example", "GARMIN_HUB_INVITE_TTL_DAYS": "3"},
    )
    assert s.invite_ttl_days == 3


@pytest.mark.parametrize("value", [None, "", "ftp://hub", "not a url"])
def test_public_url_is_required(value: str | None) -> None:
    environ = {} if value is None else {"GARMIN_HUB_PUBLIC_URL": value}
    with pytest.raises(MissingConfigError) as exc:
        load_settings({}, environ=environ)
    assert exc.value.message == "falta configuración obligatoria: GARMIN_HUB_PUBLIC_URL."


def test_public_url_normalized() -> None:
    assert Settings(public_url="http://localhost:8000/").public_url == "http://localhost:8000"


def _write_env(tmp_path: Path, env_line: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(f"{env_line}\nGARMIN_HUB_SESSION_SECRET=from-dotenv\n", encoding="utf-8")
    return path


def test_env_file_read_when_dev_in_file(tmp_path: Path) -> None:
    path = _write_env(tmp_path, "GARMIN_HUB_ENV=dev")
    assert load_env_file(path, environ={})["GARMIN_HUB_SESSION_SECRET"] == "from-dotenv"


def test_env_file_read_when_dev_in_environment(tmp_path: Path) -> None:
    path = _write_env(tmp_path, "")
    values = load_env_file(path, environ={"GARMIN_HUB_ENV": "dev"})
    assert values["GARMIN_HUB_SESSION_SECRET"] == "from-dotenv"


def test_env_file_ignored_outside_dev(tmp_path: Path) -> None:
    path = _write_env(tmp_path, "GARMIN_HUB_ENV=dev")
    assert load_env_file(path, environ={"GARMIN_HUB_ENV": "prod"}) == {}
    assert load_env_file(_write_env(tmp_path, "GARMIN_HUB_ENV=prod"), environ={}) == {}
    assert load_env_file(tmp_path / "missing.env", environ={}) == {}


def test_env_secret_provider_fallback_and_priority() -> None:
    provider = EnvSecretProvider(fallback={"A": "dotenv", "B": "dotenv"}, environ={"B": "real"})
    assert provider.get("A") == "dotenv"
    assert provider.get("B") == "real"
    assert provider.get("C") is None


def test_settings_from_env_file_values() -> None:
    s = load_settings({"GARMIN_HUB_PUBLIC_URL": "http://localhost:8000"}, environ={})
    assert s.public_url == "http://localhost:8000"
    s = load_settings(
        {"GARMIN_HUB_PUBLIC_URL": "http://localhost:8000"},
        environ={"GARMIN_HUB_PUBLIC_URL": "https://real.example"},
    )
    assert s.public_url == "https://real.example"
