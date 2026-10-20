"""Códigos de invitación y de restablecimiento (research R6)."""

import secrets

from garmin_hub.keys import DerivedKeys, hmac_digest

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # base32 de Crockford
CODE_LENGTH = 20
_TRANSLATE = str.maketrans({"O": "0", "I": "1", "L": "1"})


def generate_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return format_code(raw)


def format_code(raw: str) -> str:
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def normalize_code(code: str) -> str:
    cleaned = "".join(ch for ch in code.upper() if ch not in "- \t")
    return cleaned.translate(_TRANSLATE)


def code_hash(keys: DerivedKeys, code: str) -> bytes:
    return hmac_digest(keys.code, normalize_code(code))
