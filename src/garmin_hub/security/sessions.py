"""Sesiones en servidor (FR-018 a FR-021, research R8)."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, delete, insert, select, update

from garmin_hub.config import Settings
from garmin_hub.db.schema import app_user, user_session
from garmin_hub.keys import DerivedKeys, hmac_digest

COOKIE_NAME = "__Host-gh_session"
COOKIE_ATTRS = {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}
LAST_SEEN_RESOLUTION = timedelta(seconds=60)
PURGE_BATCH = 500


@dataclass(frozen=True)
class SessionUser:
    user_id: UUID
    email: str
    display_name: str
    role: str
    session_hash: bytes = field(repr=False)
    session_id: str = field(repr=False)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def session_hash(keys: DerivedKeys, raw_id: str) -> bytes:
    return hmac_digest(keys.session_id, raw_id)


def create_session(
    conn: Connection, user_id: UUID, keys: DerivedKeys, settings: Settings, now: datetime
) -> str:
    """Crea una sesión nueva y devuelve su id en claro (solo se guarda el HMAC)."""
    raw_id = secrets.token_urlsafe(32)
    conn.execute(
        insert(user_session).values(
            session_hash=session_hash(keys, raw_id),
            user_id=user_id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_max_hours),
        )
    )
    return raw_id


def resolve_session(
    conn: Connection, raw_id: str, keys: DerivedKeys, settings: Settings, now: datetime
) -> SessionUser | None:
    """Devuelve el usuario de una sesión válida; borra la sesión si ya no lo es."""
    s_hash = session_hash(keys, raw_id)
    row = conn.execute(
        select(
            user_session.c.last_seen_at,
            user_session.c.expires_at,
            app_user.c.user_id,
            app_user.c.email,
            app_user.c.display_name,
            app_user.c.role,
            app_user.c.status,
        )
        .join(app_user, app_user.c.user_id == user_session.c.user_id)
        .where(user_session.c.session_hash == s_hash)
    ).first()
    if row is None:
        return None
    idle = timedelta(minutes=settings.session_idle_minutes)
    if row.status != "active" or now >= row.expires_at or now - row.last_seen_at >= idle:
        conn.execute(delete(user_session).where(user_session.c.session_hash == s_hash))
        return None
    if now - row.last_seen_at >= LAST_SEEN_RESOLUTION:
        conn.execute(
            update(user_session)
            .where(user_session.c.session_hash == s_hash)
            .values(last_seen_at=now)
        )
    return SessionUser(
        user_id=row.user_id,
        email=row.email,
        display_name=row.display_name,
        role=row.role,
        session_hash=s_hash,
        session_id=raw_id,
    )


def delete_session(conn: Connection, raw_id: str, keys: DerivedKeys) -> None:
    conn.execute(
        delete(user_session).where(user_session.c.session_hash == session_hash(keys, raw_id))
    )


def delete_user_sessions(conn: Connection, user_id: UUID, except_hash: bytes | None = None) -> int:
    stmt = delete(user_session).where(user_session.c.user_id == user_id)
    if except_hash is not None:
        stmt = stmt.where(user_session.c.session_hash != except_hash)
    return conn.execute(stmt).rowcount or 0


def purge_expired_sessions(conn: Connection, settings: Settings, now: datetime) -> int:
    """Borra hasta 500 sesiones caducadas (oportunista, al iniciar sesión)."""
    idle_limit = now - timedelta(minutes=settings.session_idle_minutes)
    expired = (
        select(user_session.c.session_hash)
        .where((user_session.c.expires_at <= now) | (user_session.c.last_seen_at <= idle_limit))
        .limit(PURGE_BATCH)
    )
    hashes = [r[0] for r in conn.execute(expired)]
    if not hashes:
        return 0
    return (
        conn.execute(delete(user_session).where(user_session.c.session_hash.in_(hashes))).rowcount
        or 0
    )
