"""Una petición en curso por cuenta y una comprobación por minuto (constitución III, R6).

Ambas reclamaciones son un `UPDATE` condicional, atómico en SQL Server y en SQLite.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, or_, update

from garmin_hub.db.schema import garmin_account

_c = garmin_account.c


def acquire(conn: Connection, account_id: UUID, now: datetime, seconds: int) -> bool:
    """Reclama el candado de la cuenta; `False` si otra operación lo tiene."""
    result = conn.execute(
        update(garmin_account)
        .where(
            _c.garmin_account_id == account_id,
            or_(_c.request_lease_until.is_(None), _c.request_lease_until < now),
        )
        .values(request_lease_until=now + timedelta(seconds=seconds))
    )
    return result.rowcount == 1


def release(conn: Connection, account_id: UUID) -> None:
    conn.execute(
        update(garmin_account)
        .where(_c.garmin_account_id == account_id)
        .values(request_lease_until=None)
    )


def claim_check(conn: Connection, account_id: UUID, now: datetime, interval: int) -> bool:
    """Reclama la comprobación (FR-025); `False` si ya se comprobó hace menos de `interval` s."""
    result = conn.execute(
        update(garmin_account)
        .where(
            _c.garmin_account_id == account_id,
            or_(
                _c.last_check_started_at.is_(None),
                _c.last_check_started_at <= now - timedelta(seconds=interval),
            ),
        )
        .values(last_check_started_at=now)
    )
    return result.rowcount == 1
