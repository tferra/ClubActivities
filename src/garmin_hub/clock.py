"""Reloj UTC inyectable."""

from collections.abc import Callable
from datetime import UTC, datetime

type Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Devuelve la hora actual con zona horaria UTC."""
    return datetime.now(UTC)
