"""Cifrado de los accesos a Garmin con Fernet y versión de clave (constitución IV, research R5)."""

import base64
import binascii

from cryptography.fernet import Fernet, InvalidToken

_KEY_BYTES = 32


class UndecryptableToken(Exception):
    """El acceso no se puede descifrar: versión no configurada o contenido manipulado."""

    def __init__(self) -> None:
        super().__init__("stored token cannot be decrypted")


def _parse_key(raw: str) -> Fernet:
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise ValueError("clave no válida") from None
    if len(decoded) != _KEY_BYTES or base64.urlsafe_b64encode(decoded).decode() != raw:
        raise ValueError("clave no válida")
    return Fernet(raw.encode("ascii"))


def parse_master_keys(raw: str) -> dict[int, Fernet]:
    """Interpreta `<versión>:<clave>[,<versión>:<clave>...]`. Los errores nunca incluyen valores."""
    keys: dict[int, Fernet] = {}
    for part in raw.split(","):
        version_text, sep, key_text = part.strip().partition(":")
        if not sep or not version_text.isdigit():
            raise ValueError("formato de GARMIN_HUB_MASTER_KEYS no válido")
        version = int(version_text)
        if version <= 0 or version in keys:
            raise ValueError("versión de clave no válida o repetida")
        keys[version] = _parse_key(key_text.strip())
    if not keys:
        raise ValueError("GARMIN_HUB_MASTER_KEYS está vacío")
    return keys


class TokenCipher:
    """Cifra con la clave vigente (versión más alta) y descifra con la versión de cada fila."""

    def __init__(self, keys: dict[int, Fernet]) -> None:
        if not keys:
            raise ValueError("se necesita al menos una clave")
        self._keys = dict(keys)
        self.current_version = max(self._keys)

    def encrypt(self, data: bytes) -> tuple[bytes, int]:
        return self._keys[self.current_version].encrypt(data), self.current_version

    def decrypt(self, ciphertext: bytes, key_version: int) -> bytes:
        key = self._keys.get(key_version)
        if key is None:
            raise UndecryptableToken
        try:
            return key.decrypt(ciphertext)
        except InvalidToken:
            raise UndecryptableToken from None

    def __repr__(self) -> str:
        return f"TokenCipher(versions={sorted(self._keys)}, current={self.current_version})"

    __str__ = __repr__
