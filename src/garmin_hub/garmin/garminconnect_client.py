"""`GarminClient` sobre `garminconnect==0.3.17` (research R1, R3, R4, R5, R10 y R11).

Es el único módulo que importa la librería (lo vigila `test_garmin_import_guard.py`). Usa la
clase de bajo nivel `Client`, que no guarda la contraseña, y nunca el envoltorio `Garmin`.
El texto de las excepciones de la librería solo se usa para clasificarlas: no se muestra, no
se registra y no se propaga.
"""

import contextlib
import json
import random
import re
import time
from collections.abc import Callable
from typing import Literal

import requests
from garminconnect.client import Client
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_hub.garmin.client import (
    GarminError,
    GarminIdentity,
    GarminProtocolError,
    GarminTokens,
    GarminUnavailable,
    InvalidCredentials,
    InvalidMfaCode,
    LoginSucceeded,
    MfaPending,
    RateLimited,
    TemporarilyBlocked,
    TokenRejected,
    VerifyResult,
)
from garmin_hub.garmin.retry import Sleep, call_with_backoff, jittered

# Orden de research R11: en cada intento se salta el resto con `skip_strategies`.
STRATEGIES = ("mobile+cffi", "mobile+requests", "widget+cffi", "portal+cffi", "portal+requests")
SOCIAL_PROFILE = "/userprofile-service/socialProfile"

type Stage = Literal["login", "mfa", "api"]

_API_STATUS = re.compile(r"\bAPI Error (\d{3})\b")
_HTTP_403 = re.compile(r"\b403\b")
_HTTP_429 = re.compile(r"\b429\b")


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    match = _API_STATUS.search(str(exc))
    return int(match.group(1)) if match else None


def _is_network_error(exc: Exception) -> bool:
    if isinstance(exc, requests.RequestException | OSError | TimeoutError):
        return True
    # Los errores de transporte de curl_cffi no heredan de los de requests.
    return type(exc).__module__.startswith("curl_cffi")


def _map_exception(exc: Exception, stage: Stage) -> GarminError:
    """Único punto de traducción de las excepciones de la librería (research R10)."""
    if isinstance(exc, GarminError):
        return exc
    if isinstance(exc, GarminConnectAuthenticationError):
        return {"login": InvalidCredentials, "mfa": InvalidMfaCode, "api": TokenRejected}[stage]()
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return RateLimited()
    if isinstance(exc, GarminConnectConnectionError):
        status = _status_code(exc)
        text = str(exc)
        if status == 429 or (status is None and _HTTP_429.search(text)):
            return RateLimited()
        if stage == "api":
            if status in (401, 403):
                return TokenRejected()
            if status is None or status >= 500:
                return GarminUnavailable()
            return GarminProtocolError()
        if status == 403 or (status is None and _HTTP_403.search(text)):
            return TemporarilyBlocked()
        return GarminUnavailable()
    if _is_network_error(exc):
        return GarminUnavailable()
    return GarminProtocolError()


def _identity(profile: object) -> GarminIdentity:
    profile_id = profile.get("profileId") if isinstance(profile, dict) else None
    if not isinstance(profile_id, int) or isinstance(profile_id, bool) or profile_id <= 0:
        raise GarminProtocolError
    return GarminIdentity(profile_id)


def _persistable(dumps: str) -> GarminTokens:
    try:
        data = json.loads(dumps)
    except ValueError:
        raise GarminProtocolError from None
    # Sin token de renovación (camino JWT_WEB) el acceso no se puede guardar (R5).
    if not isinstance(data, dict) or not data.get("di_refresh_token"):
        raise GarminProtocolError
    return GarminTokens(dumps.encode())


class GarminConnectClient:
    def __init__(
        self,
        *,
        max_retries: int = 2,
        login_max_retries: int = 0,
        strategy_pause: float = 2.0,
        login_budget: float = 45.0,
        sleep: Sleep = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._login_max_retries = login_max_retries
        self._strategy_pause = strategy_pause
        self._login_budget = login_budget
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.Random()  # noqa: S311 - jitter, no criptografía

    # --- Login ------------------------------------------------------------------------

    def start_login(self, email: str, password: str) -> LoginSucceeded | MfaPending:
        return call_with_backoff(
            lambda: self._login_once(email, password),
            max_retries=self._login_max_retries,
            sleep=self._sleep,
            rng=self._rng,
        )

    def _login_once(self, email: str, password: str) -> LoginSucceeded | MfaPending:
        """Recorre las estrategias una a una, con pausa, cortes y tiempo máximo (R11)."""
        client = Client()
        started = self._clock()
        last: GarminError = GarminUnavailable()
        for index, name in enumerate(STRATEGIES):
            if index:
                if self._clock() - started >= self._login_budget:
                    raise GarminUnavailable
                self._sleep(jittered(self._strategy_pause, self._rng))
                if self._clock() - started >= self._login_budget:
                    raise GarminUnavailable
            client.skip_strategies = set(STRATEGIES) - {name}
            try:
                status, _ = client.login(email, password, return_on_mfa=True)
            except Exception as exc:
                error = _map_exception(exc, "login")
                if isinstance(error, InvalidCredentials | RateLimited | TemporarilyBlocked):
                    raise error from None
                last = error
                continue
            if status == "needs_mfa":
                return MfaPending(handle=client)
            return self._finish(client)
        raise last

    def complete_mfa(self, pending: MfaPending, code: str) -> LoginSucceeded:
        client = pending.handle
        try:
            client.resume_login(None, code)  # type: ignore[attr-defined]
        except Exception as exc:
            raise _map_exception(exc, "mfa") from None
        return self._finish(client)  # type: ignore[arg-type]

    def discard(self, pending: MfaPending) -> None:
        with contextlib.suppress(Exception):
            pending.handle._clear_auth_state()  # type: ignore[attr-defined]

    def _finish(self, client: Client) -> LoginSucceeded:
        try:
            profile = client.connectapi(SOCIAL_PROFILE)
            dumps = client.dumps()
        except Exception as exc:
            error = _map_exception(exc, "api")
            # Un acceso recién obtenido que Garmin rechaza es una respuesta inesperada.
            raise (GarminProtocolError() if isinstance(error, TokenRejected) else error) from None
        return LoginSucceeded(tokens=_persistable(dumps), identity=_identity(profile))

    # --- Verificación -----------------------------------------------------------------

    def verify(self, tokens: GarminTokens) -> VerifyResult:
        return call_with_backoff(
            lambda: self._verify_once(tokens),
            max_retries=self._max_retries,
            sleep=self._sleep,
            rng=self._rng,
        )

    def _verify_once(self, tokens: GarminTokens) -> VerifyResult:
        client = Client()
        try:
            client.loads(tokens.value.decode())
        except Exception:
            raise TokenRejected from None
        before = client.dumps()
        try:
            profile = client.connectapi(SOCIAL_PROFILE)
            after = client.dumps()
        except Exception as exc:
            raise _map_exception(exc, "api") from None
        identity = _identity(profile)
        renewed = _persistable(after) if after != before else None
        return VerifyResult(identity=identity, renewed_tokens=renewed)
