"""Exportación de los datos propios (FR-023a, constitución V).

Cada feature que guarde datos de usuario registra su sección con `register_export_section`.
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.users import get_user
from garmin_hub.db.schema import audit_event

FORMAT_VERSION = 1

type ExportSection = Callable[[Connection, UUID], Any]

_SECTIONS: dict[str, ExportSection] = {}


def register_export_section(name: str, fn: ExportSection) -> None:
    if name in _SECTIONS:
        raise ValueError(f"sección de exportación duplicada: {name}")
    _SECTIONS[name] = fn


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _profile(conn: Connection, user_id: UUID) -> dict[str, Any]:
    user = get_user(conn, user_id)
    return {
        "user_id": str(user.user_id),
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "created_at": _iso(user.created_at),
        "last_login_at": _iso(user.last_login_at),
    }


def _actor(actor_id: UUID | None, user_id: UUID) -> str | None:
    if actor_id is None:
        return None
    return "self" if actor_id == user_id else "admin"


def _audit_events(conn: Connection, user_id: UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            audit_event.c.occurred_at,
            audit_event.c.event_type,
            audit_event.c.actor_user_id,
            audit_event.c.ip_prefix,
            audit_event.c.details,
        )
        .where(audit_event.c.subject_user_id == user_id)
        .order_by(audit_event.c.occurred_at, audit_event.c.audit_id)
    )
    return [
        {
            "occurred_at": _iso(r.occurred_at),
            "event_type": r.event_type,
            "actor": "self"
            if r.actor_user_id == user_id
            else ("admin" if r.actor_user_id else None),
            "ip_prefix": r.ip_prefix,
            "details": json.loads(r.details) if r.details else {},
        }
        for r in rows
    ]


register_export_section("profile", _profile)
register_export_section("audit_events", _audit_events)


def build_export(
    conn: Connection, user_id: UUID, *, ip_prefix: str | None, now: datetime
) -> dict[str, Any]:
    data: dict[str, Any] = {"format_version": FORMAT_VERSION, "exported_at": _iso(now)}
    for name, fn in _SECTIONS.items():
        data[name] = fn(conn, user_id)
    record_event(
        conn,
        "user.data_exported",
        actor_user_id=user_id,
        subject_user_id=user_id,
        ip_prefix=ip_prefix,
        details={"sections": list(_SECTIONS)},
        now=now,
    )
    return data
