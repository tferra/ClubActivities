"""Acceso a secretos a través de `SecretProvider` (constitución IV y VII, research R13)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

REQUIRED_SECRETS = ("GARMIN_HUB_DB_URL", "GARMIN_HUB_SESSION_SECRET")
MIN_SESSION_SECRET_BYTES = 32


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class EnvSecretProvider:
    """Lee secretos de las variables de entorno y, si no están, de `fallback` (el `.env`)."""

    def __init__(
        self,
        fallback: Mapping[str, str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._fallback = dict(fallback or {})
        self._environ = os.environ if environ is None else environ

    def get(self, name: str) -> str | None:
        value = self._environ.get(name)
        if value:
            return value
        return self._fallback.get(name) or None


@dataclass(frozen=True)
class Secrets:
    db_url: str = field(repr=False)
    session_secret: bytes = field(repr=False)


class MissingSecretsError(Exception):
    """Faltan secretos obligatorios o no son válidos. Nunca contiene valores."""

    def __init__(self, missing: list[str], invalid: list[str] | None = None) -> None:
        self.missing = missing
        self.invalid = invalid or []
        super().__init__(self.message)

    @property
    def message(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"faltan secretos obligatorios: {', '.join(self.missing)}.")
        if self.invalid:
            parts.append(
                f"secretos no válidos: {', '.join(self.invalid)} "
                f"(GARMIN_HUB_SESSION_SECRET necesita al menos {MIN_SESSION_SECRET_BYTES} bytes)."
            )
        return " ".join(parts)


def load_secrets(provider: SecretProvider) -> Secrets:
    """Comprueba los secretos obligatorios de la feature 001 (FR-001)."""
    values = {name: provider.get(name) for name in REQUIRED_SECRETS}
    missing = [name for name, value in values.items() if not value]
    invalid: list[str] = []
    session_secret = values["GARMIN_HUB_SESSION_SECRET"]
    if session_secret and len(session_secret.encode()) < MIN_SESSION_SECRET_BYTES:
        invalid.append("GARMIN_HUB_SESSION_SECRET")
    if missing or invalid:
        raise MissingSecretsError(missing, invalid)
    assert values["GARMIN_HUB_DB_URL"] is not None  # noqa: S101
    assert session_secret is not None  # noqa: S101
    return Secrets(db_url=values["GARMIN_HUB_DB_URL"], session_secret=session_secret.encode())
