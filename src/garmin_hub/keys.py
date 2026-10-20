"""Derivación de subclaves HMAC desde `GARMIN_HUB_SESSION_SECRET` (research R7)."""

import hashlib
import hmac
from dataclasses import dataclass, field

LABELS = ("session-id", "csrf", "code", "email-rl", "ip-rl", "anon-csrf")


@dataclass(frozen=True)
class DerivedKeys:
    session_id: bytes = field(repr=False)
    csrf: bytes = field(repr=False)
    code: bytes = field(repr=False)
    email_rl: bytes = field(repr=False)
    ip_rl: bytes = field(repr=False)
    anon_csrf: bytes = field(repr=False)


def _derive(secret: bytes, label: str) -> bytes:
    return hmac.new(secret, label.encode(), hashlib.sha256).digest()


def derive_keys(session_secret: bytes) -> DerivedKeys:
    return DerivedKeys(
        **{label.replace("-", "_"): _derive(session_secret, label) for label in LABELS}
    )


def hmac_digest(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()
