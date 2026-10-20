from pathlib import Path

import pytest

from garmin_hub.config import MissingConfigError, Settings, load_env_file, load_settings
from garmin_hub.secrets import EnvSecretProvider, MissingSecretsError, load_secrets

GOOD_SECRET = "s" * 40


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
        "faltan secretos obligatorios: GARMIN_HUB_DB_URL, GARMIN_HUB_SESSION_SECRET."
    )


def test_missing_one_secret_does_not_leak_the_other_value() -> None:
    with pytest.raises(MissingSecretsError) as exc:
        load_secrets(FakeProvider({"GARMIN_HUB_DB_URL": "mssql://u:supersecret@h/db"}))
    assert "GARMIN_HUB_SESSION_SECRET" in exc.value.message
    assert "supersecret" not in exc.value.message


def test_short_session_secret_is_rejected() -> None:
    with pytest.raises(MissingSecretsError) as exc:
        load_secrets(FakeProvider({"GARMIN_HUB_DB_URL": "x", "GARMIN_HUB_SESSION_SECRET": "short"}))
    assert exc.value.invalid == ["GARMIN_HUB_SESSION_SECRET"]
    assert "short" not in exc.value.message


def test_load_secrets_ok() -> None:
    secrets = load_secrets(
        FakeProvider({"GARMIN_HUB_DB_URL": "x", "GARMIN_HUB_SESSION_SECRET": GOOD_SECRET})
    )
    assert secrets.session_secret == GOOD_SECRET.encode()
    assert GOOD_SECRET not in repr(secrets)


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
