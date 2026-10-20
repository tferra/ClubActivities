"""Aviso de datos versionado (FR-011, FR-012, research R13).

Cambiar el texto obliga a crear `web/templates/garmin/notice_v<N>.html` y subir la constante.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, exists, insert, select
from sqlalchemy.exc import IntegrityError

from garmin_hub.accounts.audit import record_event
from garmin_hub.db.schema import data_notice_acceptance

NOTICE_VERSION = 1


def current_version() -> int:
    return NOTICE_VERSION


def template_name() -> str:
    return f"garmin/notice_v{current_version()}.html"


def has_accepted_current(conn: Connection, user_id: UUID) -> bool:
    return bool(
        conn.execute(
            select(
                exists().where(
                    data_notice_acceptance.c.user_id == user_id,
                    data_notice_acceptance.c.notice_version == current_version(),
                )
            )
        ).scalar()
    )


def accept(conn: Connection, user_id: UUID, now: datetime, ip_prefix: str | None) -> bool:
    """Registra la aceptación de la versión vigente. Es idempotente: audita solo si inserta."""
    if has_accepted_current(conn, user_id):
        return False
    version = current_version()
    try:
        conn.execute(
            insert(data_notice_acceptance).values(
                user_id=user_id, notice_version=version, accepted_at=now
            )
        )
    except IntegrityError:
        # Otra petición simultánea la ha registrado; el error solo anula esta sentencia.
        return False
    record_event(
        conn,
        "garmin.notice_accepted",
        actor_user_id=user_id,
        subject_user_id=user_id,
        ip_prefix=ip_prefix,
        details={"notice_version": version},
        now=now,
    )
    return True
