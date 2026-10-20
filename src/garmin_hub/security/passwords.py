"""Hash argon2 y política de contraseñas (FR-015 a FR-017, research R4 y R5)."""

import gzip
import re
import unicodedata
from functools import cache
from importlib import resources
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128

MSG_TOO_SHORT = f"La contraseña debe tener al menos {MIN_LENGTH} caracteres."
MSG_TOO_LONG = f"La contraseña no puede tener más de {MAX_LENGTH} caracteres."
MSG_REPEATED = "La contraseña no puede ser un único carácter repetido."
MSG_COMMON = "La contraseña es demasiado común; elige otra."
MSG_CONTAINS_EMAIL = "La contraseña no puede contener tu correo."
MSG_CONTAINS_NAME = "La contraseña no puede contener tu nombre."
MSG_CONFIRM_MISMATCH = "Las contraseñas no coinciden."

_hasher = PasswordHasher()
_NAME_SEPARATORS = re.compile(r"[\s\-'\u2019]+")


def normalize(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    return _hasher.hash(normalize(password))


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, normalize(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return _hasher.hash("garmin-hub dummy password for timing")


def verify_dummy(password: str = "") -> bool:
    """Verificación señuelo para igualar tiempos cuando no hay usuario (SC-005)."""
    verify_password(_dummy_hash(), password or "x")
    return False


def load_common_passwords(path: Path | None = None) -> frozenset[str]:
    """Carga la lista vendorizada (o un `.gz` concreto, para tests)."""
    if path is None:
        return _default_common_passwords()
    return _read_gz(path.read_bytes())


@cache
def _default_common_passwords() -> frozenset[str]:
    data = resources.files("garmin_hub.security").joinpath("data/common_passwords.txt.gz")
    return _read_gz(data.read_bytes())


def _read_gz(raw: bytes) -> frozenset[str]:
    text = gzip.decompress(raw).decode("utf-8")
    return frozenset(line for line in text.splitlines() if line)


def validate_password(
    password: str,
    *,
    email: str,
    display_name: str,
    common: frozenset[str] | None = None,
) -> str | None:
    """Devuelve el mensaje en español de la regla incumplida, o `None` si es válida."""
    pw = normalize(password)
    if len(pw) < MIN_LENGTH:
        return MSG_TOO_SHORT
    if len(pw) > MAX_LENGTH:
        return MSG_TOO_LONG
    if len(set(pw)) == 1:
        return MSG_REPEATED
    folded = pw.casefold()
    if common is None:
        common = load_common_passwords()
    if pw.lower() in common:
        return MSG_COMMON
    local = normalize(email.split("@", 1)[0]).casefold()
    if len(local) >= 4 and local in folded:
        return MSG_CONTAINS_EMAIL
    for word in _NAME_SEPARATORS.split(normalize(display_name)):
        word = word.casefold()
        if len(word) >= 4 and word in folded:
            return MSG_CONTAINS_NAME
    return None
