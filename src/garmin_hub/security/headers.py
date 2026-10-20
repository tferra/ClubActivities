"""Cabeceras de seguridad (constitución IV, research R12)."""

from garmin_hub.asgi_types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
HSTS = "max-age=31536000"
PERMISSIONS_POLICY = "geolocation=(), camera=(), microphone=()"


class SecurityHeadersMiddleware:
    """Añade las cabeceras de R12; `Cache-Control: no-store` si la petición es autenticada."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                authenticated = _authenticated(scope)
                replaced = {b"content-security-policy"}
                if authenticated:
                    replaced.add(b"cache-control")
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() not in replaced
                ]
                headers += [
                    (b"content-security-policy", CSP.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"same-origin"),
                    (b"permissions-policy", PERMISSIONS_POLICY.encode()),
                ]
                if self.hsts:
                    headers.append((b"strict-transport-security", HSTS.encode()))
                if authenticated:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _authenticated(scope: Scope) -> bool:
    state = scope.get("state") or {}
    return bool(state.get("authenticated"))
