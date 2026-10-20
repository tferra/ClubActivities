"""Intentos de login a la espera del código MFA, en la memoria del proceso web (research R3).

Lo permite la excepción de la constitución VII (v1.1.0): el estado dura como máximo
`GARMIN_HUB_GARMIN_MFA_TTL_MINUTES`, no contiene ni el correo ni la contraseña y perderlo solo
obliga a repetir el login. Requiere un único proceso web o afinidad de sesión.
"""

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from garmin_hub.garmin.client import MfaPending

type Purpose = Literal["link", "reauth"]


class _Discarder(Protocol):
    def discard(self, pending: MfaPending) -> None: ...


class RegistryFull(Exception):
    """Se ha alcanzado el tope global de intentos pendientes."""


@dataclass
class PendingLogin:
    attempt_id: str
    user_id: UUID
    purpose: Purpose
    garmin_account_id: UUID | None
    alias: str | None
    mfa_required_at: datetime
    expires_at: datetime
    pending: MfaPending
    mfa_failures: int = 0

    def remaining_seconds(self, now: datetime) -> int:
        return max(0, int((self.expires_at - now).total_seconds()))


class PendingLoginRegistry:
    def __init__(
        self,
        *,
        ttl: timedelta,
        clock: Callable[[], datetime],
        client: _Discarder,
        max_entries: int = 100,
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._client = client
        self._max_entries = max_entries
        self._entries: dict[str, PendingLogin] = {}
        self._lock = threading.Lock()

    def _drop(self, attempt_id: str) -> None:
        entry = self._entries.pop(attempt_id, None)
        if entry is not None:
            self._client.discard(entry.pending)

    def _purge(self, now: datetime) -> None:
        for attempt_id in [a for a, e in self._entries.items() if now > e.expires_at]:
            self._drop(attempt_id)

    def add(
        self,
        *,
        user_id: UUID,
        purpose: Purpose,
        garmin_account_id: UUID | None,
        alias: str | None,
        pending: MfaPending,
    ) -> PendingLogin:
        """Guarda un intento; descarta el anterior del mismo usuario (uno por usuario)."""
        now = self._clock()
        with self._lock:
            self._purge(now)
            for attempt_id in [a for a, e in self._entries.items() if e.user_id == user_id]:
                self._drop(attempt_id)
            if len(self._entries) >= self._max_entries:
                self._client.discard(pending)
                raise RegistryFull
            entry = PendingLogin(
                attempt_id=secrets.token_urlsafe(16),
                user_id=user_id,
                purpose=purpose,
                garmin_account_id=garmin_account_id,
                alias=alias,
                mfa_required_at=now,
                expires_at=now + self._ttl,
                pending=pending,
            )
            self._entries[entry.attempt_id] = entry
            return entry

    def get(self, attempt_id: str, user_id: UUID) -> PendingLogin | None:
        """El intento vivo de ese usuario; `None` si no existe, caducó o es de otro usuario."""
        with self._lock:
            self._purge(self._clock())
            entry = self._entries.get(attempt_id)
            if entry is None or entry.user_id != user_id:
                return None
            return entry

    def pop(self, attempt_id: str, user_id: UUID) -> PendingLogin | None:
        """Retira el intento sin liberarlo (el login se ha completado)."""
        with self._lock:
            entry = self._entries.get(attempt_id)
            if entry is None or entry.user_id != user_id:
                return None
            return self._entries.pop(attempt_id)

    def discard_for_user(self, user_id: UUID) -> None:
        with self._lock:
            for attempt_id in [a for a, e in self._entries.items() if e.user_id == user_id]:
                self._drop(attempt_id)

    def discard_for_account(self, garmin_account_id: UUID) -> None:
        with self._lock:
            for attempt_id in [
                a for a, e in self._entries.items() if e.garmin_account_id == garmin_account_id
            ]:
                self._drop(attempt_id)
