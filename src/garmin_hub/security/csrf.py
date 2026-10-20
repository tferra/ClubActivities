"""CSRF con sesión, doble envío anónimo y comprobación de `Origin` (FR-033, research R9)."""

import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from starlette.requests import Request

from garmin_hub.keys import DerivedKeys
from garmin_hub.security.sessions import COOKIE_NAME as SESSION_COOKIE

ANON_COOKIE = "__Host-gh_csrf"
HEADER = "X-CSRF-Token"
FIELD = "csrf_token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CsrfError(Exception):
    """Token CSRF ausente o no válido, u `Origin` ajeno."""


def _token(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def session_token(keys: DerivedKeys, session_id: str) -> str:
    return _token(keys.csrf, session_id)


def anon_token(keys: DerivedKeys, nonce: str) -> str:
    return _token(keys.anon_csrf, nonce)


def new_anon_pair(keys: DerivedKeys) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(32)
    return nonce, anon_token(keys, nonce)


def verify(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def origin_ok(origin: str | None, public_url: str) -> bool:
    if origin is None:
        return True
    parts = urlsplit(origin)
    return f"{parts.scheme}://{parts.netloc}" == public_url


async def require_csrf(request: Request) -> None:
    """Dependencia de router: exige token en POST/PUT/PATCH/DELETE.

    `request.form()` queda en caché en el mismo `Request`, así la ruta recibe sus campos.
    """
    if request.method in SAFE_METHODS:
        return
    state = request.app.state
    if not origin_ok(request.headers.get("origin"), state.settings.public_url):
        raise CsrfError
    provided = request.headers.get(HEADER)
    if provided is None:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()
            value = form.get(FIELD)
            provided = value if isinstance(value, str) else None
    keys: DerivedKeys = state.keys
    candidates = []
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        candidates.append(session_token(keys, session_id))
    nonce = request.cookies.get(ANON_COOKIE)
    if nonce:
        candidates.append(anon_token(keys, nonce))
    if not any(verify(expected, provided) for expected in candidates):
        raise CsrfError
