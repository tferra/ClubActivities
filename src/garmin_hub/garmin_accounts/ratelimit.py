"""Límite de logins fallidos en Garmin por usuario (FR-010, research R9).

Solo cuentan las credenciales y los códigos MFA rechazados por Garmin; la comprobación se hace
antes de contactar con Garmin.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, delete, func, insert, select

from garmin_hub.db.schema import garmin_login_failure

RETENTION = timedelta(hours=24)

_c = garmin_login_failure.c


def is_blocked(
    conn: Connection, user_id: UUID, now: datetime, max_failures: int, window: timedelta
) -> bool:
    failures = conn.execute(
        select(func.count())
        .select_from(garmin_login_failure)
        .where(_c.user_id == user_id, _c.failed_at > now - window)
    ).scalar_one()
    return failures >= max_failures


def record_failure(conn: Connection, user_id: UUID, now: datetime) -> None:
    conn.execute(insert(garmin_login_failure).values(user_id=user_id, failed_at=now))
    purge_old(conn, now)


def purge_old(conn: Connection, now: datetime) -> int:
    """Borra los fallos de más de 24 horas (oportunista)."""
    return conn.execute(delete(garmin_login_failure).where(_c.failed_at < now - RETENTION)).rowcount
