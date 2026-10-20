"""Límite de intentos (FR-030, FR-030a, FR-031, research R10)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import Connection, delete, false, func, insert, select, true

from garmin_hub.config import Settings
from garmin_hub.db.schema import login_attempt
from garmin_hub.keys import DerivedKeys, hmac_digest
from garmin_hub.security.ip import ip_hmac


class Outcome(StrEnum):
    ALLOW = "allow"
    BLOCKED_PAIR = "blocked_pair"
    BLOCKED_IP = "blocked_ip"


class Kind(StrEnum):
    LOGIN = "login"
    CODE_REDEEM = "code_redeem"
    CURRENT_PASSWORD = "current_password"  # noqa: S105


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    delay: float = 0.0
    email_failures: int = 0

    @property
    def allowed(self) -> bool:
        return self.outcome is Outcome.ALLOW

    def crossed_soft_limit(self, settings: Settings) -> bool:
        """Verdadero solo en el intento que cruza el umbral global por correo."""
        return self.email_failures == settings.login_email_soft_limit


def decide(
    pair_failures: int, ip_failures: int, email_failures_1h: int, settings: Settings
) -> Decision:
    """Función pura de decisión: bloqueo por par, por IP y retardo global por correo."""
    if pair_failures >= settings.login_pair_max_failures:
        outcome = Outcome.BLOCKED_PAIR
    elif ip_failures >= settings.login_ip_max_failures:
        outcome = Outcome.BLOCKED_IP
    else:
        outcome = Outcome.ALLOW
    delay = 0.0
    soft = settings.login_email_soft_limit
    if email_failures_1h >= soft:
        delay = min(settings.login_email_max_delay_seconds, 0.5 * (email_failures_1h - soft + 1))
    return Decision(outcome=outcome, delay=delay, email_failures=email_failures_1h)


def email_hmac(keys: DerivedKeys, email: str) -> bytes:
    return hmac_digest(keys.email_rl, email)


def _count(conn: Connection, *conditions: object) -> int:
    t = login_attempt
    stmt = select(func.count()).select_from(t).where(t.c.succeeded == false(), *conditions)
    return int(conn.execute(stmt).scalar_one())


def check_attempts(
    conn: Connection,
    *,
    email: str | None,
    ip: str,
    kind: Kind,
    keys: DerivedKeys,
    settings: Settings,
    now: datetime,
) -> Decision:
    """Cuenta los fallos recientes y devuelve la decisión.

    No duerme: la ruta espera el retardo fuera de la transacción (R10).
    """
    t = login_attempt
    ip_h = ip_hmac(keys, ip)
    pair_failures = ip_failures = email_failures = 0

    if email is not None and kind in (Kind.LOGIN, Kind.CURRENT_PASSWORD):
        email_h = email_hmac(keys, email)
        last_success = conn.execute(
            select(func.max(t.c.attempted_at)).where(
                t.c.email_hmac == email_h,
                t.c.ip_hmac == ip_h,
                t.c.kind == Kind.LOGIN.value,
                t.c.succeeded == true(),
            )
        ).scalar_one_or_none()
        since = now - timedelta(minutes=settings.login_pair_window_minutes)
        if last_success is not None and last_success > since:
            since = last_success
        pair_failures = _count(
            conn,
            t.c.email_hmac == email_h,
            t.c.ip_hmac == ip_h,
            t.c.kind.in_([Kind.LOGIN.value, Kind.CURRENT_PASSWORD.value]),
            t.c.attempted_at > since,
        )
        if kind is Kind.LOGIN:
            email_failures = _count(
                conn,
                t.c.email_hmac == email_h,
                t.c.kind == Kind.LOGIN.value,
                t.c.attempted_at
                > now - timedelta(minutes=settings.login_email_soft_window_minutes),
            )

    if kind in (Kind.LOGIN, Kind.CODE_REDEEM):
        ip_failures = _count(
            conn,
            t.c.ip_hmac == ip_h,
            t.c.kind.in_([Kind.LOGIN.value, Kind.CODE_REDEEM.value]),
            t.c.attempted_at > now - timedelta(minutes=settings.login_ip_window_minutes),
        )
    return decide(pair_failures, ip_failures, email_failures, settings)


def record_attempt(
    conn: Connection,
    *,
    email: str | None,
    ip: str,
    kind: Kind,
    succeeded: bool,
    keys: DerivedKeys,
    now: datetime,
) -> None:
    """Guarda el intento con el correo y la dirección seudonimizados, nunca en claro."""
    conn.execute(
        insert(login_attempt).values(
            attempted_at=now,
            email_hmac=email_hmac(keys, email) if email is not None else None,
            ip_hmac=ip_hmac(keys, ip),
            kind=kind.value,
            succeeded=succeeded,
        )
    )


def purge_old_attempts(conn: Connection, now: datetime) -> int:
    t = login_attempt
    result = conn.execute(delete(t).where(t.c.attempted_at < now - timedelta(hours=24)))
    return result.rowcount or 0
