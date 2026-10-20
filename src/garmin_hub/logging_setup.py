"""Logging JSON sin secretos ni datos personales (research R14)."""

import ipaddress
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from garmin_hub.asgi_types import ASGIApp, Message, Receive, Scope, Send
from garmin_hub.config import Settings
from garmin_hub.security.ip import UNKNOWN, ip_prefix

MASK = "***"
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "pass",
        "secret",
        "token",
        "code",
        "cookie",
        "authorization",
        "session",
        "csrf",
        "email",
        "ip",
        "client",
        "remote_addr",
        "db_url",
    }
)
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)

_URL_PASSWORD = re.compile(r"(//[^:/@\s]+:)[^@\s]+@")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CODE = re.compile(r"\b[0-9A-Za-z]{4}(?:-[0-9A-Za-z]{4}){4}\b")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w./])")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:/])")


def _mask_ip(match: re.Match[str]) -> str:
    try:
        ipaddress.ip_address(match.group(0))
    except ValueError:
        return match.group(0)
    return MASK


def redact_text(text: str) -> str:
    text = _URL_PASSWORD.sub(rf"\g<1>{MASK}@", text)
    text = _EMAIL.sub(MASK, text)
    text = _CODE.sub(MASK, text)
    text = _IPV4.sub(_mask_ip, text)
    return _IPV6.sub(_mask_ip, text)


def is_sensitive_key(key: str) -> bool:
    key = key.lower()
    return key in SENSITIVE_KEYS or key.split("_")[-1] in SENSITIVE_KEYS


def _redact_value(key: str, value: Any) -> Any:
    if is_sensitive_key(key):
        return MASK
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    """Enmascara claves sensibles en `extra`/`args` y patrones sensibles en el mensaje."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict):
            record.args = {k: _redact_value(str(k), v) for k, v in record.args.items()}
        for key in list(vars(record)):
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                setattr(record, key, _redact_value(key, getattr(record, key)))
        record.msg = redact_text(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


THIRD_PARTY_LOGGERS = ("garminconnect", "curl_cffi")
THIRD_PARTY_MESSAGE = "third-party library error (details suppressed)"


class ThirdPartyLogScrubber(logging.Filter):
    """Sustituye el contenido de los logs de la librería de Garmin por un texto fijo (R17).

    Solo se conservan el nombre del logger y el nivel: la librería puede incluir URL, cuerpos
    de respuesta o datos de la cuenta en sus mensajes y excepciones.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = THIRD_PARTY_MESSAGE
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        for key in list(vars(record)):
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                delattr(record, key)
        return True


class JsonFormatter(logging.Formatter):
    """Una línea JSON por evento."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                data[key] = value
        if record.exc_text:
            data["exc"] = record.exc_text
        elif record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


_HANDLER_MARK = "_garmin_hub_handler"


class _ScrubbingHandler(logging.Handler):
    """Pasa los registros de terceros por `ThirdPartyLogScrubber` antes de los handlers comunes.

    Los filtros de un logger no se aplican a los registros de sus hijos
    (`garminconnect.client`), así que el filtro va en un handler propio.
    """

    def __init__(self, targets: list[logging.Handler]) -> None:
        super().__init__()
        self.targets = targets
        self.addFilter(ThirdPartyLogScrubber())

    def emit(self, record: logging.LogRecord) -> None:
        for target in self.targets:
            if record.levelno >= target.level:
                target.handle(record)


def configure_logging(settings: Settings) -> None:
    """stderr + fichero rotativo, ambos con `RedactingFilter`."""
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        RotatingFileHandler(
            settings.log_dir / "garmin-hub.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RedactingFilter())
        setattr(handler, _HANDLER_MARK, True)
    for name in ("garmin_hub", "uvicorn.error", "uvicorn", *THIRD_PARTY_LOGGERS):
        logger = logging.getLogger(name)
        for old in [h for h in logger.handlers if getattr(h, _HANDLER_MARK, False)]:
            logger.removeHandler(old)
            old.close()
    scrubber = _ScrubbingHandler(handlers)
    setattr(scrubber, _HANDLER_MARK, True)
    for name in THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.ERROR)
        logger.propagate = False
        logger.addHandler(scrubber)
    app_logger = logging.getLogger("garmin_hub")
    app_logger.setLevel(settings.log_level.upper())
    app_logger.propagate = False
    for handler in handlers:
        app_logger.addHandler(handler)
    uv_logger = logging.getLogger("uvicorn.error")
    uv_logger.propagate = False
    for handler in handlers:
        uv_logger.addHandler(handler)


class AccessLogMiddleware:
    """Log de acceso propio: sin query string y solo con el prefijo de red (R11, R14)."""

    def __init__(self, app: ASGIApp, logger_name: str = "garmin_hub.access") -> None:
        self.app = app
        self.logger = logging.getLogger(logger_name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            client = scope.get("client")
            prefix = ip_prefix(client[0]) if client else UNKNOWN
            self.logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "ip_prefix": prefix,
                },
            )
