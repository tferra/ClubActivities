"""Interfaz propia de acceso a Garmin (contracts/garmin-client.md, research R2).

Ningún tipo de la librería sale de aquí: los servicios solo ven estos resultados y errores.
"""

from dataclasses import dataclass, field
from typing import ClassVar, Protocol


@dataclass(frozen=True)
class GarminTokens:
    """Accesos opacos (JSON de `Client.dumps()`); nunca se muestran."""

    value: bytes = field(repr=False)

    def __str__(self) -> str:
        return "GarminTokens(***)"


@dataclass(frozen=True)
class GarminIdentity:
    profile_id: int = field(repr=False)


@dataclass(frozen=True)
class LoginSucceeded:
    tokens: GarminTokens
    identity: GarminIdentity


@dataclass(frozen=True, eq=False)
class MfaPending:
    """Login a la espera del código; `handle` solo lo entiende la implementación que lo creó."""

    handle: object = field(repr=False)


@dataclass(frozen=True)
class VerifyResult:
    identity: GarminIdentity
    renewed_tokens: GarminTokens | None = None


class GarminError(Exception):
    """Error de Garmin con un texto fijo en inglés, sin contenido de la librería."""

    message: ClassVar[str] = "garmin error"

    def __init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class InvalidCredentials(GarminError):
    message = "garmin rejected the credentials"


class InvalidMfaCode(GarminError):
    message = "garmin rejected the verification code"


class RateLimited(GarminError):
    message = "garmin is rate limiting requests"


class TemporarilyBlocked(GarminError):
    message = "garmin temporarily blocked the login"


class GarminUnavailable(GarminError):
    message = "garmin is not reachable"


class TokenRejected(GarminError):
    message = "garmin no longer accepts the stored token"


class GarminProtocolError(GarminError):
    message = "garmin returned an unexpected response"


class GarminClient(Protocol):
    def start_login(self, email: str, password: str) -> LoginSucceeded | MfaPending: ...

    def complete_mfa(self, pending: MfaPending, code: str) -> LoginSucceeded: ...

    def discard(self, pending: MfaPending) -> None: ...

    def verify(self, tokens: GarminTokens) -> VerifyResult: ...
