"""Registro de auditoría de solo inserción (FR-034, FR-035, contracts/audit-events.md)."""

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, insert

from garmin_hub.db.schema import audit_event

ALLOWED_DETAILS: dict[str, frozenset[str]] = {
    "admin.created": frozenset({"via"}),
    "invitation.created": frozenset({"invitation_id", "ttl_days"}),
    "invitation.revoked": frozenset({"invitation_id"}),
    "user.signed_up": frozenset({"invitation_id"}),
    "auth.login_succeeded": frozenset(),
    "auth.login_failed": frozenset({"reason"}),
    "auth.email_soft_limit": frozenset({"failures_1h"}),
    "auth.code_redeem_failed": frozenset({"kind", "reason"}),
    "auth.logout": frozenset(),
    "user.name_changed": frozenset(),
    "user.data_exported": frozenset({"sections"}),
    "user.password_changed": frozenset({"sessions_closed"}),
    "user.password_change_failed": frozenset(),
    "reset.created": frozenset({"reset_id"}),
    "reset.used": frozenset({"reset_id", "sessions_closed"}),
    "user.deactivated": frozenset({"sessions_closed", "resets_expired"}),
    "user.reactivated": frozenset(),
    "user.deletion_requested": frozenset({"by"}),
    "user.deletion_step_failed": frozenset({"step"}),
    "user.deleted": frozenset({"by", "steps"}),
    # Feature 002 (specs/002-garmin-account-linking/contracts/audit-events.md).
    "garmin.notice_accepted": frozenset({"notice_version"}),
    "garmin.account_linked": frozenset({"garmin_account_id", "recovered", "mfa"}),
    "garmin.link_failed": frozenset({"reason"}),
    "garmin.reauthenticated": frozenset({"garmin_account_id", "mfa"}),
    "garmin.reauth_failed": frozenset({"garmin_account_id", "reason"}),
    "garmin.status_changed": frozenset({"garmin_account_id", "from", "to", "via", "error_code"}),
    "garmin.account_checked": frozenset({"garmin_account_id", "result"}),
    "garmin.account_unlinked": frozenset({"garmin_account_id", "data"}),
    "garmin.data_deletion_requested": frozenset({"garmin_account_id"}),
    "garmin.account_deletion_step_failed": frozenset({"garmin_account_id", "step"}),
    "garmin.account_deleted": frozenset({"garmin_account_id", "steps"}),
}

_PREFIX = re.compile(r"^(unknown|[0-9.]+/24|[0-9A-Fa-f:]+/48)$")


def record_event(
    conn: Connection,
    event_type: str,
    *,
    actor_user_id: UUID | None,
    subject_user_id: UUID | None,
    ip_prefix: str | None,
    details: dict[str, Any] | None = None,
    now: datetime,
) -> None:
    """Inserta un evento. Rechaza tipos y claves de `details` fuera de la lista blanca."""
    if event_type not in ALLOWED_DETAILS:
        raise ValueError(f"tipo de evento no permitido: {event_type}")
    details = details or {}
    extra = set(details) - ALLOWED_DETAILS[event_type]
    if extra:
        raise ValueError(f"claves de details no permitidas para {event_type}: {sorted(extra)}")
    if ip_prefix is not None and not _PREFIX.match(ip_prefix):
        raise ValueError("ip_prefix debe ser una red reducida, no una dirección completa")
    conn.execute(
        insert(audit_event).values(
            occurred_at=now,
            event_type=event_type,
            actor_user_id=actor_user_id,
            subject_user_id=subject_user_id,
            ip_prefix=ip_prefix,
            details=json.dumps(details, ensure_ascii=False, default=str, sort_keys=True),
        )
    )
