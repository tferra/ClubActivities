"""Login real contra Garmin Connect (research R16). Nunca se ejecuta por defecto.

Uso, con una cuenta Garmin propia y las variables solo en la sesión de terminal:

    GARMIN_HUB_LIVE_GARMIN_EMAIL=... GARMIN_HUB_LIVE_GARMIN_PASSWORD=... uv run pytest -m live -s

Si la cuenta tiene MFA, el test pide el código por consola. Los accesos nunca se imprimen ni se
guardan.
"""

import json
import logging
import os
import time
import warnings

import pytest

from garmin_hub.garmin.client import LoginSucceeded, MfaPending
from garmin_hub.garmin.garminconnect_client import GarminConnectClient

pytestmark = pytest.mark.live

LOGIN_TARGET_SECONDS = 45


# `_clean_env` (tests/conftest.py) borra GARMIN_HUB_* antes de cada test: se leen al importar.
LIVE_EMAIL = os.environ.get("GARMIN_HUB_LIVE_GARMIN_EMAIL")
LIVE_PASSWORD = os.environ.get("GARMIN_HUB_LIVE_GARMIN_PASSWORD")


@pytest.fixture
def credentials() -> tuple[str, str]:
    if not LIVE_EMAIL or not LIVE_PASSWORD:
        pytest.skip("faltan GARMIN_HUB_LIVE_GARMIN_EMAIL o GARMIN_HUB_LIVE_GARMIN_PASSWORD")
    return LIVE_EMAIL, LIVE_PASSWORD


def test_real_login_and_verify(credentials, caplog) -> None:
    email, password = credentials
    caplog.set_level(logging.DEBUG)
    client = GarminConnectClient()
    started = time.monotonic()
    result = client.start_login(email, password)
    elapsed = time.monotonic() - started
    if isinstance(result, MfaPending):
        code = input("Código de verificación de Garmin: ").strip()
        result = client.complete_mfa(result, code)
    assert isinstance(result, LoginSucceeded)
    assert result.identity.profile_id > 0
    assert json.loads(result.tokens.value)["di_refresh_token"]

    verified = client.verify(result.tokens)
    assert verified.identity == result.identity

    text = caplog.text
    assert email not in text
    assert password not in text
    if elapsed > LOGIN_TARGET_SECONDS:
        warnings.warn(f"login de Garmin lento: {elapsed:.1f} s (SC-001)", stacklevel=1)
    print(f"\nDuración de start_login: {elapsed:.1f} s")  # dato para SC-001
