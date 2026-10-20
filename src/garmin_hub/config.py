"""Configuración no secreta (pydantic-settings) y lectura de `.env` en desarrollo (research R13)."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "GARMIN_HUB_"
CONFIG_HINTS = {"GARMIN_HUB_GARMIN_CLIENT": "fake solo en dev o test"}


class MissingConfigError(Exception):
    """Falta configuración obligatoria o no es válida."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(self.message)

    @property
    def message(self) -> str:
        hints = [CONFIG_HINTS[name] for name in self.names if name in CONFIG_HINTS]
        suffix = f" ({'; '.join(hints)})" if hints else ""
        return f"falta configuración obligatoria: {', '.join(self.names)}{suffix}."


def load_env_file(
    path: Path = Path(".env"), environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Devuelve las variables de `.env` solo si `GARMIN_HUB_ENV=dev`.

    `GARMIN_HUB_ENV` se toma del entorno real o, si no está ahí, del propio fichero.
    """
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return {}
    values = {k: v for k, v in dotenv_values(path).items() if v is not None}
    env = environ.get(f"{ENV_PREFIX}ENV") or values.get(f"{ENV_PREFIX}ENV")
    if env != "dev":
        return {}
    return values


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore", frozen=True)

    env: Literal["dev", "test", "prod"] = "prod"
    public_url: str
    db_schema: str = "gh"
    trusted_proxies: str = "127.0.0.1"
    log_dir: Path = Path("logs")
    log_level: str = "INFO"

    invite_ttl_days: int = 7
    reset_ttl_hours: int = 24
    session_idle_minutes: int = 30
    session_max_hours: int = 12
    login_pair_max_failures: int = 5
    login_pair_window_minutes: int = 15
    login_ip_max_failures: int = 20
    login_ip_window_minutes: int = 15
    login_email_soft_limit: int = 50
    login_email_soft_window_minutes: int = 60
    login_email_max_delay_seconds: float = 10

    # Cuentas Garmin (feature 002, data-model.md "Configuración nueva").
    garmin_client: Literal["garminconnect", "fake"] = "garminconnect"
    garmin_mfa_ttl_minutes: int = 5
    garmin_max_accounts: int = 10
    garmin_login_max_failures: int = 5
    garmin_login_window_minutes: int = 15
    garmin_check_interval_seconds: int = 60
    garmin_request_lease_seconds: int = 120
    garmin_max_retries: int = 2
    garmin_login_max_retries: int = 0
    garmin_login_strategy_pause_seconds: float = 2
    garmin_login_budget_seconds: float = 45

    @field_validator("public_url")
    @classmethod
    def _check_public_url(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("debe ser una URL http(s)")
        return f"{parts.scheme}://{parts.netloc}"

    @field_validator("db_schema")
    @classmethod
    def _check_schema(cls, value: str) -> str:
        if not value.replace("_", "").isalnum():
            raise ValueError("solo letras, números y _")
        return value

    @field_validator("garmin_client")
    @classmethod
    def _check_garmin_client(cls, value: str, info: ValidationInfo) -> str:
        # `env` se declara antes, así que ya está validado (research R18).
        if value == "fake" and info.data.get("env", "prod") == "prod":
            raise ValueError("el cliente falso solo se permite en dev o test")
        return value

    @property
    def is_https(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def public_origin(self) -> str:
        return self.public_url


def load_settings(
    env_file_values: Mapping[str, str] | None = None, environ: Mapping[str, str] | None = None
) -> Settings:
    """Construye `Settings` con el entorno real por encima de los valores de `.env`."""
    environ = os.environ if environ is None else environ
    merged: dict[str, str] = {}
    for source in (env_file_values or {}, environ):
        for key, value in source.items():
            if key.startswith(ENV_PREFIX) and value != "":
                merged[key[len(ENV_PREFIX) :].lower()] = value
    fields = Settings.model_fields
    try:
        return Settings(**{k: v for k, v in merged.items() if k in fields})  # type: ignore[arg-type]
    except ValidationError as exc:
        names = sorted({f"{ENV_PREFIX}{str(err['loc'][0]).upper()}" for err in exc.errors()})
        raise MissingConfigError(names) from None
