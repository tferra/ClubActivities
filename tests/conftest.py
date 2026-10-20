"""Fixtures compartidas: configuración, secretos sintéticos, reloj y sleep falsos."""

import gzip
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from garmin_hub.config import Settings
from garmin_hub.keys import DerivedKeys, derive_keys
from garmin_hub.secrets import Secrets

TEST_SESSION_SECRET = b"test-session-secret-0123456789-abcdefghijklmnop"
TEST_DB_URL = "mssql+pyodbc://tester:db-secret-pw@localhost:1433/garmin?driver=X"
# Clave de test generada en cada ejecución; nunca se guarda.
TEST_MASTER_KEYS = f"1:{Fernet.generate_key().decode()}"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los tests no dependen de las variables GARMIN_HUB_* del entorno del desarrollador."""
    import os

    for name in list(os.environ):
        if name.startswith("GARMIN_HUB_") and name != "GARMIN_HUB_TEST_DB_URL":
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _restore_loggers() -> Iterator[None]:
    """`configure_logging` (CLI) cambia loggers globales; se restauran tras cada test."""
    import logging

    names = ("garmin_hub", "uvicorn.error", "uvicorn", "garminconnect", "curl_cffi")
    saved = {
        n: (
            list(logging.getLogger(n).handlers),
            logging.getLogger(n).propagate,
            logging.getLogger(n).level,
        )
        for n in names
    }
    yield
    for name, (handlers, propagate, level) in saved.items():
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.handlers = handlers
        logger.propagate = propagate
        logger.setLevel(level)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(env="test", public_url="https://testserver", log_dir=tmp_path / "logs")


@pytest.fixture
def secrets() -> Secrets:
    return Secrets(
        db_url=TEST_DB_URL, session_secret=TEST_SESSION_SECRET, master_keys=TEST_MASTER_KEYS
    )


@pytest.fixture
def keys(secrets: Secrets) -> DerivedKeys:
    return derive_keys(secrets.session_secret)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_sleep() -> FakeSleep:
    return FakeSleep()


@pytest.fixture
def common_passwords(tmp_path: Path) -> Path:
    path = tmp_path / "common.txt.gz"
    path.write_bytes(gzip.compress(b"correcthorsebattery\npassword123456\n"))
    return path
