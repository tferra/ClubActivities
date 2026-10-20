"""Mensajes en español y motivos de auditoría de los errores de Garmin (research R6 a R10)."""

from garmin_hub.garmin.client import (
    GarminError,
    GarminProtocolError,
    GarminUnavailable,
    InvalidCredentials,
    InvalidMfaCode,
    RateLimited,
    TemporarilyBlocked,
    TokenRejected,
)

# R10: errores de Garmin.
MSG_BAD_CREDENTIALS = "Garmin no acepta ese correo o contraseña."
MSG_BAD_MFA = "El código de verificación no es correcto."
MSG_MFA_EXPIRED = "El intento ha caducado; vuelve a empezar."
MSG_RATE_LIMITED = "Garmin está limitando las peticiones; inténtalo dentro de un rato."
MSG_BLOCKED = "Garmin ha bloqueado temporalmente el inicio de sesión; inténtalo más tarde."
MSG_UNAVAILABLE = "No se ha podido conectar con Garmin; inténtalo más tarde."
MSG_TOKEN_REJECTED = "Garmin ya no acepta el acceso guardado; vuelve a autenticar la cuenta."  # noqa: S105
MSG_PROTOCOL = "Garmin ha respondido de forma inesperada; inténtalo más tarde."
MSG_TOKEN_UNDECRYPTABLE = "No se puede usar el acceso guardado; vuelve a autenticar la cuenta."  # noqa: S105
MSG_IDENTITY_MISMATCH = (
    "El acceso guardado corresponde a otra cuenta Garmin; vuelve a autenticarla."
)
MSG_REAUTH_OTHER_IDENTITY = "Esas credenciales son de otra cuenta Garmin distinta de «{alias}»."
MSG_CHECK_OK = "Funciona correctamente."
# R3: registro de intentos MFA lleno.
MSG_REGISTRY_FULL = "Garmin no está disponible en este momento; inténtalo más tarde."

# R6: candado y comprobaciones.
MSG_BUSY = "Hay otra operación en curso con esta cuenta; inténtalo en unos segundos."
MSG_CHECK_TOO_SOON = "Ya se ha comprobado hace menos de un minuto."
MSG_CHANGED = "La cuenta ha cambiado mientras se comprobaba; recarga la página."
MSG_STATE_NOT_ALLOWED = "Esta acción no está disponible en el estado actual de la cuenta."

# R7 y R8: alias, duplicados, recuperación y máximo de cuentas.
MSG_ALIAS_INVALID = "El alias debe tener entre 1 y 50 caracteres."
MSG_ALIAS_TAKEN = "Ya tienes una cuenta Garmin con ese alias."
MSG_ALREADY_LINKED_SELF = "Ya tienes vinculada esta cuenta Garmin como «{alias}»."
MSG_LINKED_ELSEWHERE = "Esta cuenta Garmin ya está vinculada a otro usuario de garmin-hub."
MSG_LIMIT_REACHED = "Has alcanzado el máximo de {limit} cuentas Garmin vinculadas."

# R9: límite de intentos.
MSG_THROTTLED = "Has hecho demasiados intentos con Garmin; espera unos minutos."

# R14: borrado.
MSG_CONFIRMATION = "Escribe el alias de la cuenta para confirmar."
MSG_MODE_REQUIRED = "Elige si quieres conservar o borrar los datos."
MSG_DELETION_FAILED = "No se ha podido completar el borrado; inténtalo de nuevo."

_MESSAGES: dict[type[GarminError], str] = {
    InvalidCredentials: MSG_BAD_CREDENTIALS,
    InvalidMfaCode: MSG_BAD_MFA,
    RateLimited: MSG_RATE_LIMITED,
    TemporarilyBlocked: MSG_BLOCKED,
    GarminUnavailable: MSG_UNAVAILABLE,
    TokenRejected: MSG_TOKEN_REJECTED,
    GarminProtocolError: MSG_PROTOCOL,
}
_REASONS: dict[type[GarminError], str] = {
    InvalidCredentials: "bad_credentials",
    InvalidMfaCode: "bad_mfa",
    RateLimited: "rate_limited",
    TemporarilyBlocked: "blocked",
    GarminUnavailable: "unavailable",
    TokenRejected: "protocol",
    GarminProtocolError: "protocol",
}

# Motivo que se muestra en el listado para las cuentas en "Error" (contracts/http.md).
ERROR_CODE_MESSAGES = {
    "token_undecryptable": MSG_TOKEN_UNDECRYPTABLE,
    "identity_mismatch": MSG_IDENTITY_MISMATCH,
}


def message_for(error: GarminError) -> str:
    return _MESSAGES.get(type(error), MSG_PROTOCOL)


def reason_for(error: GarminError) -> str:
    return _REASONS.get(type(error), "protocol")


def counts_as_failure(error: GarminError) -> bool:
    """Solo los rechazos de Garmin que pueden provocar un bloqueo cuentan para R9."""
    return isinstance(error, InvalidCredentials | InvalidMfaCode)
