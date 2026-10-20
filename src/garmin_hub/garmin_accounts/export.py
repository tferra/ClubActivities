"""Secciones de exportación de las cuentas Garmin (FR-030, data-model.md "Registros ampliables").

Nunca incluyen los accesos (cifrados o no), su versión de clave ni la identidad en Garmin.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from garmin_hub.accounts.export import register_export_section
from garmin_hub.db.schema import data_notice_acceptance
from garmin_hub.garmin_accounts.accounts import list_accounts


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _garmin_accounts(conn: Connection, user_id: UUID) -> list[dict[str, Any]]:
    return [
        {
            "garmin_account_id": str(a.garmin_account_id),
            "alias": a.alias,
            "status": a.status,
            "linked_at": _iso(a.linked_at),
            "last_login_at": _iso(a.last_login_at),
            "last_sync_at": _iso(a.last_sync_at),
            "last_checked_at": _iso(a.last_checked_at),
            "unlinked_at": _iso(a.unlinked_at),
        }
        for a in list_accounts(conn, user_id)
    ]


def _notice_acceptances(conn: Connection, user_id: UUID) -> list[dict[str, Any]]:
    c = data_notice_acceptance.c
    rows = conn.execute(
        select(c.notice_version, c.accepted_at)
        .where(c.user_id == user_id)
        .order_by(c.notice_version)
    )
    return [{"notice_version": r.notice_version, "accepted_at": _iso(r.accepted_at)} for r in rows]


register_export_section("garmin_accounts", _garmin_accounts)
register_export_section("data_notice_acceptances", _notice_acceptances)
