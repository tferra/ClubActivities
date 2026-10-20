"""Cliente de Garmin falso y determinista para tests y demo (contracts/garmin-client.md, R18).

`correcta` y `123456` son valores de prueba que solo existen en este cliente.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from garmin_hub.garmin.client import (
    GarminError,
    GarminIdentity,
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

FAKE_PASSWORD = "correcta"  # noqa: S105 - valor de prueba del cliente falso
FAKE_MFA_CODE = "123456"
REJECTED_FROM_PROFILE_ID = 9000

_ACCOUNT_EMAIL = re.compile(r"(ok|mfa)\+(\d+)@example\.test")
_SPECIAL: dict[str, type[GarminError]] = {
    "ratelimit@example.test": RateLimited,
    "blocked@example.test": TemporarilyBlocked,
    "down@example.test": GarminUnavailable,
}

# Resultado programado de `verify`: "ok", "renew", un error, otro profile_id (identidad
# distinta) o una función que recibe los accesos y devuelve el resultado.
type VerifyOutcome = (
    str | int | GarminError | type[GarminError] | Callable[[GarminTokens], VerifyResult]
)


@dataclass
class _FakeHandle:
    profile_id: int
    discarded: bool = False


class FakeGarminClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        # Operación → función que se ejecuta una vez justo antes de devolver (tests de carreras).
        self.hooks: dict[str, Callable[[], None]] = {}
        # Texto adicional dentro de los accesos y contraseña aceptada (test de centinelas).
        self.token_extra: str | None = None
        self.password = FAKE_PASSWORD
        self._verify_script: dict[int, VerifyOutcome] = {}
        self._revisions: dict[int, int] = {}

    def script_verify(self, profile_id: int, outcome: VerifyOutcome) -> None:
        self._verify_script[profile_id] = outcome

    def _run_hook(self, operation: str) -> None:
        hook = self.hooks.pop(operation, None)
        if hook is not None:
            hook()

    def _tokens(self, profile_id: int) -> GarminTokens:
        revision = self._revisions.get(profile_id, 0) + 1
        self._revisions[profile_id] = revision
        data: dict[str, object] = {"fake": profile_id, "rev": revision}
        if self.token_extra is not None:
            data["x"] = self.token_extra
        return GarminTokens(json.dumps(data, separators=(",", ":")).encode())

    def _succeeded(self, profile_id: int) -> LoginSucceeded:
        return LoginSucceeded(tokens=self._tokens(profile_id), identity=GarminIdentity(profile_id))

    def start_login(self, email: str, password: str) -> LoginSucceeded | MfaPending:
        self.calls.append(("start_login", email))
        if email in _SPECIAL:
            raise _SPECIAL[email]()
        match = _ACCOUNT_EMAIL.fullmatch(email)
        if match is None or password != self.password:
            raise InvalidCredentials
        profile_id = int(match.group(2))
        result: LoginSucceeded | MfaPending
        if match.group(1) == "mfa":
            result = MfaPending(handle=_FakeHandle(profile_id))
        else:
            result = self._succeeded(profile_id)
        self._run_hook("start_login")
        return result

    def complete_mfa(self, pending: MfaPending, code: str) -> LoginSucceeded:
        self.calls.append(("complete_mfa",))
        handle = pending.handle
        if not isinstance(handle, _FakeHandle) or handle.discarded:
            raise GarminUnavailable
        if code != FAKE_MFA_CODE:
            raise InvalidMfaCode
        result = self._succeeded(handle.profile_id)
        self._run_hook("complete_mfa")
        return result

    def discard(self, pending: MfaPending) -> None:
        self.calls.append(("discard",))
        if isinstance(pending.handle, _FakeHandle):
            pending.handle.discarded = True

    def verify(self, tokens: GarminTokens) -> VerifyResult:
        self.calls.append(("verify",))
        profile_id = int(json.loads(tokens.value)["fake"])
        outcome = self._verify_script.get(profile_id)
        result = self._verify_outcome(profile_id, tokens, outcome)
        self._run_hook("verify")
        return result

    def _verify_outcome(
        self, profile_id: int, tokens: GarminTokens, outcome: VerifyOutcome | None
    ) -> VerifyResult:
        if outcome is None:
            if profile_id >= REJECTED_FROM_PROFILE_ID:
                raise TokenRejected
            outcome = "ok"
        if isinstance(outcome, GarminError):
            raise outcome
        if isinstance(outcome, type) and issubclass(outcome, GarminError):
            raise outcome()
        if callable(outcome):
            return outcome(tokens)
        if outcome == "renew":
            return VerifyResult(GarminIdentity(profile_id), self._tokens(profile_id))
        if isinstance(outcome, int):
            return VerifyResult(GarminIdentity(outcome))
        return VerifyResult(GarminIdentity(profile_id))
