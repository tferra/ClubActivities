"""Cuentas Garmin del usuario: propiedad, alias, accesos cifrados y servicios (research R6 a R15).

Todas las consultas de una cuenta filtran por `garmin_account_id` **y** `user_id` (R15). Las
llamadas a Garmin se hacen fuera de cualquier transacción (R12) y las escrituras posteriores
son condicionales, para no resucitar una cuenta desvinculada mientras tanto (R6).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection, Engine, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from garmin_hub.accounts.audit import record_event
from garmin_hub.accounts.users import lock_user
from garmin_hub.config import Settings
from garmin_hub.db.schema import ACTIVE_STATUSES, LIVE_STATUSES, garmin_account, garmin_token
from garmin_hub.garmin.client import (
    GarminClient,
    GarminError,
    GarminTokens,
    InvalidMfaCode,
    LoginSucceeded,
    MfaPending,
    TokenRejected,
)
from garmin_hub.garmin.pending import PendingLogin, PendingLoginRegistry, RegistryFull
from garmin_hub.garmin_accounts import lease, ratelimit
from garmin_hub.garmin_accounts.errors import (
    MSG_ALIAS_INVALID,
    MSG_ALIAS_TAKEN,
    MSG_ALREADY_LINKED_SELF,
    MSG_BUSY,
    MSG_CHANGED,
    MSG_CHECK_OK,
    MSG_CHECK_TOO_SOON,
    MSG_IDENTITY_MISMATCH,
    MSG_LIMIT_REACHED,
    MSG_LINKED_ELSEWHERE,
    MSG_MFA_EXPIRED,
    MSG_REAUTH_OTHER_IDENTITY,
    MSG_REGISTRY_FULL,
    MSG_STATE_NOT_ALLOWED,
    MSG_THROTTLED,
    MSG_TOKEN_REJECTED,
    MSG_TOKEN_UNDECRYPTABLE,
    counts_as_failure,
    message_for,
    reason_for,
)
from garmin_hub.security.token_cipher import TokenCipher, UndecryptableToken

_c = garmin_account.c

ALIAS_MAX = 50


@dataclass(frozen=True)
class AccountRow:
    garmin_account_id: UUID
    user_id: UUID
    alias: str
    garmin_profile_id: int = field(repr=False)
    status: str
    error_code: str | None
    linked_at: datetime
    last_login_at: datetime
    last_sync_at: datetime | None
    last_checked_at: datetime | None
    unlinked_at: datetime | None
    deletion_requested_at: datetime | None
    created_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


_ACCOUNT_COLUMNS = (
    _c.garmin_account_id,
    _c.user_id,
    _c.alias,
    _c.garmin_profile_id,
    _c.status,
    _c.error_code,
    _c.linked_at,
    _c.last_login_at,
    _c.last_sync_at,
    _c.last_checked_at,
    _c.unlinked_at,
    _c.deletion_requested_at,
    _c.created_at,
)


def _row(mapping: Any) -> AccountRow:
    return AccountRow(**mapping)


def parse_account_id(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except (ValueError, TypeError, AttributeError):
        return None


def get_own_account(conn: Connection, user_id: UUID, account_id: UUID) -> AccountRow | None:
    """La cuenta si es de `user_id`; `None` si no existe o es de otro (indistinguible, R15)."""
    row = conn.execute(
        select(*_ACCOUNT_COLUMNS).where(_c.garmin_account_id == account_id, _c.user_id == user_id)
    ).first()
    return _row(row._mapping) if row else None


def normalize_alias(alias: str) -> tuple[str, str] | None:
    """`(alias, alias_key)` con el alias sin espacios alrededor; `None` si no es válido (FR-006)."""
    alias = alias.strip()
    if not 1 <= len(alias) <= ALIAS_MAX:
        return None
    return alias, alias.casefold()


def count_active(conn: Connection, user_id: UUID) -> int:
    """Cuentas que cuentan para el máximo (R8): `valid`, `reauth_required` y `error`."""
    return conn.execute(
        select(func.count())
        .select_from(garmin_account)
        .where(_c.user_id == user_id, _c.status.in_(ACTIVE_STATUSES))
    ).scalar_one()


def update_if_active(conn: Connection, account_id: UUID, values: dict[str, Any]) -> bool:
    """Escribe en la cuenta solo si sigue vinculada (R6); indica si ha afectado a una fila."""
    result = conn.execute(
        update(garmin_account)
        .where(_c.garmin_account_id == account_id, _c.status.in_(ACTIVE_STATUSES))
        .values(**values)
    )
    return result.rowcount == 1


def save_token(
    conn: Connection,
    account_id: UUID,
    tokens: GarminTokens,
    cipher: TokenCipher,
    now: datetime,
    *,
    renewed: bool = False,
) -> None:
    """Guarda el acceso cifrado con la clave vigente.

    Con `renewed=True` (renovación en `verify`) conserva `issued_at`; si no, lo reemplaza.
    """
    ciphertext, version = cipher.encrypt(tokens.value)
    if renewed:
        result = conn.execute(
            update(garmin_token)
            .where(garmin_token.c.garmin_account_id == account_id)
            .values(ciphertext=ciphertext, key_version=version, updated_at=now)
        )
        if result.rowcount == 1:
            return
    conn.execute(delete(garmin_token).where(garmin_token.c.garmin_account_id == account_id))
    conn.execute(
        insert(garmin_token).values(
            garmin_account_id=account_id,
            ciphertext=ciphertext,
            key_version=version,
            issued_at=now,
            updated_at=now,
        )
    )


def load_tokens(conn: Connection, account_id: UUID, cipher: TokenCipher) -> GarminTokens:
    """Descifra el acceso de la cuenta; `UndecryptableToken` si no existe o no se puede usar."""
    row = conn.execute(
        select(garmin_token.c.ciphertext, garmin_token.c.key_version).where(
            garmin_token.c.garmin_account_id == account_id
        )
    ).first()
    if row is None:
        raise UndecryptableToken
    return GarminTokens(cipher.decrypt(row.ciphertext, row.key_version))


def delete_token(conn: Connection, account_id: UUID) -> None:
    conn.execute(delete(garmin_token).where(garmin_token.c.garmin_account_id == account_id))


# --- Resultados y fallos de los servicios -------------------------------------------------

type FailureKind = Literal["invalid", "conflict", "throttled", "expired"]


class GarminActionFailed(Exception):
    """La acción no se ha podido completar; `message` va en español para el usuario.

    `kind` decide el código HTTP: `invalid` 422, `conflict` 409, `throttled` 429, `expired` 410.
    """

    def __init__(
        self, message: str, kind: FailureKind = "invalid", reason: str | None = None
    ) -> None:
        self.message = message
        self.kind = kind
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class Linked:
    garmin_account_id: UUID
    recovered: bool


@dataclass(frozen=True)
class Reauthenticated:
    garmin_account_id: UUID


@dataclass(frozen=True)
class NeedsMfa:
    attempt: PendingLogin


@dataclass(frozen=True)
class GarminContext:
    """Dependencias de los servicios que hablan con Garmin (las da `app.state`)."""

    engine: Engine
    client: GarminClient
    registry: PendingLoginRegistry
    cipher: TokenCipher
    settings: Settings


def _audit(
    engine: Engine,
    event_type: str,
    user_id: UUID,
    ip_prefix: str | None,
    now: datetime,
    details: dict[str, Any],
) -> None:
    with engine.begin() as conn:
        record_event(
            conn,
            event_type,
            actor_user_id=user_id,
            subject_user_id=user_id,
            ip_prefix=ip_prefix,
            details=details,
            now=now,
        )


def _audit_failure(
    ctx: GarminContext,
    event_type: str,
    exc: GarminActionFailed,
    user_id: UUID,
    ip_prefix: str | None,
    now: datetime,
    **details: Any,
) -> None:
    """Audita un fallo con su `reason` (los errores de validación no llevan y no se auditan)."""
    if exc.reason:
        _audit(ctx.engine, event_type, user_id, ip_prefix, now, {**details, "reason": exc.reason})


def _check_throttle(ctx: GarminContext, conn: Connection, user_id: UUID, now: datetime) -> None:
    settings = ctx.settings
    if ratelimit.is_blocked(
        conn,
        user_id,
        now,
        settings.garmin_login_max_failures,
        timedelta(minutes=settings.garmin_login_window_minutes),
    ):
        raise GarminActionFailed(MSG_THROTTLED, "throttled", "throttled")


def _check_limit(ctx: GarminContext, conn: Connection, user_id: UUID) -> None:
    limit = ctx.settings.garmin_max_accounts
    if count_active(conn, user_id) >= limit:
        raise GarminActionFailed(MSG_LIMIT_REACHED.format(limit=limit), "conflict", "limit_reached")


def _garmin_failed(
    ctx: GarminContext, error: GarminError, user_id: UUID, now: datetime
) -> GarminActionFailed:
    """Traduce un error de Garmin y anota el fallo si cuenta para el límite de R9."""
    if counts_as_failure(error):
        with ctx.engine.begin() as conn:
            ratelimit.record_failure(conn, user_id, now)
    return GarminActionFailed(message_for(error), "invalid", reason_for(error))


def can_start_link(ctx: GarminContext, user_id: UUID) -> str | None:
    """Mensaje si el usuario ya tiene el máximo de cuentas (para el GET del formulario)."""
    with ctx.engine.connect() as conn:
        try:
            _check_limit(ctx, conn, user_id)
        except GarminActionFailed as exc:
            return exc.message
    return None


# --- Vinculación (US1, research R7, R8 y R12) ---------------------------------------------


def start_link(
    ctx: GarminContext,
    *,
    user_id: UUID,
    alias: str,
    email: str,
    password: str,
    now: datetime,
    ip_prefix: str | None,
) -> Linked | NeedsMfa:
    """Valida, hace el login en Garmin fuera de transacción y guarda la cuenta o el intento MFA.

    El correo y la contraseña solo se pasan al cliente de Garmin; no se guardan ni se registran.
    """
    normalized = normalize_alias(alias)
    if normalized is None:
        raise GarminActionFailed(MSG_ALIAS_INVALID)
    try:
        with ctx.engine.connect() as conn:
            _check_throttle(ctx, conn, user_id, now)
            _check_limit(ctx, conn, user_id)
        try:
            result = ctx.client.start_login(email, password)
        except GarminError as error:
            raise _garmin_failed(ctx, error, user_id, now) from None
        if isinstance(result, MfaPending):
            try:
                attempt = ctx.registry.add(
                    user_id=user_id,
                    purpose="link",
                    garmin_account_id=None,
                    alias=normalized[0],
                    pending=result,
                )
            except RegistryFull:
                raise GarminActionFailed(MSG_REGISTRY_FULL, "invalid", "unavailable") from None
            return NeedsMfa(attempt)
        return _persist_link(
            ctx, user_id, normalized[0], result, mfa=False, now=now, ip_prefix=ip_prefix
        )
    except GarminActionFailed as exc:
        _audit_failure(ctx, "garmin.link_failed", exc, user_id, ip_prefix, now)
        raise


def complete_mfa(
    ctx: GarminContext,
    *,
    user_id: UUID,
    attempt_id: str,
    code: str,
    now: datetime,
    ip_prefix: str | None,
) -> Linked | Reauthenticated:
    """Completa con el código MFA el intento pendiente, de vinculación o de reautenticación."""
    attempt = ctx.registry.get(attempt_id, user_id)
    if attempt is None:
        _audit(ctx.engine, "garmin.link_failed", user_id, ip_prefix, now, {"reason": "mfa_expired"})
        raise GarminActionFailed(MSG_MFA_EXPIRED, "expired")
    if attempt.purpose == "reauth":
        return _complete_reauth_mfa(ctx, attempt, code=code, now=now, ip_prefix=ip_prefix)
    try:
        with ctx.engine.connect() as conn:
            _check_throttle(ctx, conn, user_id, now)
        try:
            result = ctx.client.complete_mfa(attempt.pending, code)
        except GarminError as error:
            if isinstance(error, InvalidMfaCode):
                attempt.mfa_failures += 1
            raise _garmin_failed(ctx, error, user_id, now) from None
        ctx.registry.pop(attempt.attempt_id, user_id)
        return _persist_link(
            ctx, user_id, attempt.alias or "", result, mfa=True, now=now, ip_prefix=ip_prefix
        )
    except GarminActionFailed as exc:
        _audit_failure(ctx, "garmin.link_failed", exc, user_id, ip_prefix, now)
        raise


def cancel_mfa(ctx: GarminContext, *, user_id: UUID, attempt_id: str) -> None:
    if ctx.registry.get(attempt_id, user_id) is not None:
        ctx.registry.discard_for_user(user_id)


def _live_account_for_identity(
    conn: Connection, user_id: UUID, profile_id: int
) -> AccountRow | None:
    row = conn.execute(
        select(*_ACCOUNT_COLUMNS).where(
            _c.user_id == user_id,
            _c.garmin_profile_id == profile_id,
            _c.status.in_(LIVE_STATUSES),
        )
    ).first()
    return _row(row._mapping) if row else None


def _alias_in_use(conn: Connection, user_id: UUID, alias_key: str) -> bool:
    return (
        conn.execute(
            select(_c.garmin_account_id).where(
                _c.user_id == user_id, _c.alias_key == alias_key, _c.status.in_(LIVE_STATUSES)
            )
        ).first()
        is not None
    )


def recover_if_unlinked(
    ctx: GarminContext,
    conn: Connection,
    existing: AccountRow,
    result: LoginSucceeded,
    now: datetime,
) -> Linked | None:
    """Reactiva la cuenta `unlinked` del propio usuario (R7, paso 3, y US5-4).

    Conserva el identificador, el alias original y los datos. Si otro usuario tiene ahora la
    identidad vinculada, el índice de identidad activa lanza `IntegrityError` (FR-007).
    """
    if existing.status != "unlinked":
        return None
    _check_limit(ctx, conn, existing.user_id)
    conn.execute(
        update(garmin_account)
        .where(_c.garmin_account_id == existing.garmin_account_id, _c.status == "unlinked")
        .values(
            status="valid",
            error_code=None,
            unlinked_at=None,
            last_login_at=now,
            request_lease_until=None,
            updated_at=now,
        )
    )
    save_token(conn, existing.garmin_account_id, result.tokens, ctx.cipher, now)
    return Linked(existing.garmin_account_id, recovered=True)


def _persist_link(
    ctx: GarminContext,
    user_id: UUID,
    alias: str,
    result: LoginSucceeded,
    *,
    mfa: bool,
    now: datetime,
    ip_prefix: str | None,
) -> Linked:
    """Guarda la cuenta tras un login correcto, en una transacción con el usuario bloqueado."""
    normalized = normalize_alias(alias)
    if normalized is None:
        raise GarminActionFailed(MSG_ALIAS_INVALID)
    alias, alias_key = normalized
    profile_id = result.identity.profile_id
    try:
        with ctx.engine.begin() as conn:
            lock_user(conn, user_id)
            existing = _live_account_for_identity(conn, user_id, profile_id)
            if existing is not None and existing.is_active:
                raise GarminActionFailed(
                    MSG_ALREADY_LINKED_SELF.format(alias=existing.alias),
                    "invalid",
                    "already_linked_self",
                )
            linked = None
            if existing is not None:
                linked = recover_if_unlinked(ctx, conn, existing, result, now)
            if linked is None:
                if _alias_in_use(conn, user_id, alias_key):
                    raise GarminActionFailed(MSG_ALIAS_TAKEN, "invalid", "alias_taken")
                _check_limit(ctx, conn, user_id)
                account_id = uuid.uuid4()
                conn.execute(
                    insert(garmin_account).values(
                        garmin_account_id=account_id,
                        user_id=user_id,
                        alias=alias,
                        alias_key=alias_key,
                        garmin_profile_id=profile_id,
                        status="valid",
                        linked_at=now,
                        last_login_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                save_token(conn, account_id, result.tokens, ctx.cipher, now)
                linked = Linked(account_id, recovered=False)
            record_event(
                conn,
                "garmin.account_linked",
                actor_user_id=user_id,
                subject_user_id=user_id,
                ip_prefix=ip_prefix,
                details={
                    "garmin_account_id": str(linked.garmin_account_id),
                    "recovered": linked.recovered,
                    "mfa": mfa,
                },
                now=now,
            )
    except IntegrityError:
        # El índice de identidad activa: otro usuario la tiene vinculada (FR-007).
        raise GarminActionFailed(MSG_LINKED_ELSEWHERE, "invalid", "linked_elsewhere") from None
    return linked


# --- Reautenticación (US4, FR-018, FR-019, research R6) -----------------------------------


def _claim_for_garmin(
    ctx: GarminContext, conn: Connection, user_id: UUID, account_id: UUID, now: datetime
) -> AccountRow:
    """Valida el estado, el límite de intentos y reclama el candado antes de llamar a Garmin."""
    account = get_own_account(conn, user_id, account_id)
    if account is None or not account.is_active:
        raise GarminActionFailed(MSG_STATE_NOT_ALLOWED, "conflict")
    _check_throttle(ctx, conn, user_id, now)
    if not lease.acquire(conn, account_id, now, ctx.settings.garmin_request_lease_seconds):
        raise GarminActionFailed(MSG_BUSY, "conflict", "busy")
    return account


def _release(ctx: GarminContext, account_id: UUID) -> None:
    with ctx.engine.begin() as conn:
        lease.release(conn, account_id)


def start_reauth(
    ctx: GarminContext,
    *,
    user_id: UUID,
    account_id: UUID,
    email: str,
    password: str,
    now: datetime,
    ip_prefix: str | None,
) -> Reauthenticated | NeedsMfa:
    """Login nuevo para una cuenta existente; conserva su id, su alias y sus datos (FR-019)."""
    try:
        with ctx.engine.begin() as conn:
            account = _claim_for_garmin(ctx, conn, user_id, account_id, now)
        try:
            try:
                result = ctx.client.start_login(email, password)
            except GarminError as error:
                raise _garmin_failed(ctx, error, user_id, now) from None
            if isinstance(result, MfaPending):
                try:
                    attempt = ctx.registry.add(
                        user_id=user_id,
                        purpose="reauth",
                        garmin_account_id=account_id,
                        alias=None,
                        pending=result,
                    )
                except RegistryFull:
                    raise GarminActionFailed(MSG_REGISTRY_FULL, "invalid", "unavailable") from None
                return NeedsMfa(attempt)
            return _persist_reauth(ctx, account, result, mfa=False, now=now, ip_prefix=ip_prefix)
        finally:
            _release(ctx, account_id)
    except GarminActionFailed as exc:
        _audit_failure(
            ctx,
            "garmin.reauth_failed",
            exc,
            user_id,
            ip_prefix,
            now,
            garmin_account_id=str(account_id),
        )
        raise


def _complete_reauth_mfa(
    ctx: GarminContext,
    attempt: PendingLogin,
    *,
    code: str,
    now: datetime,
    ip_prefix: str | None,
) -> Reauthenticated:
    user_id = attempt.user_id
    account_id = attempt.garmin_account_id
    assert account_id is not None  # noqa: S101 - los intentos de reautenticación lo llevan
    try:
        with ctx.engine.begin() as conn:
            account = _claim_for_garmin(ctx, conn, user_id, account_id, now)
        try:
            try:
                result = ctx.client.complete_mfa(attempt.pending, code)
            except GarminError as error:
                if isinstance(error, InvalidMfaCode):
                    attempt.mfa_failures += 1
                raise _garmin_failed(ctx, error, user_id, now) from None
            ctx.registry.pop(attempt.attempt_id, user_id)
            return _persist_reauth(ctx, account, result, mfa=True, now=now, ip_prefix=ip_prefix)
        finally:
            _release(ctx, account_id)
    except GarminActionFailed as exc:
        _audit_failure(
            ctx,
            "garmin.reauth_failed",
            exc,
            user_id,
            ip_prefix,
            now,
            garmin_account_id=str(account_id),
        )
        raise


def _persist_reauth(
    ctx: GarminContext,
    account: AccountRow,
    result: LoginSucceeded,
    *,
    mfa: bool,
    now: datetime,
    ip_prefix: str | None,
) -> Reauthenticated:
    """Guarda el acceso nuevo si la identidad coincide y la cuenta sigue vinculada (R6)."""
    if result.identity.profile_id != account.garmin_profile_id:
        # No cuenta para el límite de R9 (US4-2): Garmin ha aceptado las credenciales.
        raise GarminActionFailed(
            MSG_REAUTH_OTHER_IDENTITY.format(alias=account.alias), "invalid", "identity_mismatch"
        )
    account_id = account.garmin_account_id
    with ctx.engine.begin() as conn:
        values = {"status": "valid", "error_code": None, "last_login_at": now, "updated_at": now}
        if not update_if_active(conn, account_id, values):
            # Se ha desvinculado mientras tanto: el acceso nuevo se descarta (FR-021).
            raise GarminActionFailed(MSG_CHANGED, "conflict")
        save_token(conn, account_id, result.tokens, ctx.cipher, now)
        record_event(
            conn,
            "garmin.reauthenticated",
            actor_user_id=account.user_id,
            subject_user_id=account.user_id,
            ip_prefix=ip_prefix,
            details={"garmin_account_id": str(account_id), "mfa": mfa},
            now=now,
        )
    return Reauthenticated(account_id)


# --- Comprobación (US7, FR-016, FR-017, FR-024, FR-025, research R6 y R10) ---------------


@dataclass(frozen=True)
class CheckOutcome:
    message: str
    ok: bool


def _status_change(
    conn: Connection,
    account: AccountRow,
    to: str,
    via: str,
    now: datetime,
    ip_prefix: str | None,
    error_code: str | None = None,
) -> None:
    if account.status == to and account.error_code == error_code:
        return
    details: dict[str, Any] = {
        "garmin_account_id": str(account.garmin_account_id),
        "from": account.status,
        "to": to,
        "via": via,
    }
    if error_code:
        details["error_code"] = error_code
    record_event(
        conn,
        "garmin.status_changed",
        actor_user_id=account.user_id,
        subject_user_id=account.user_id,
        ip_prefix=ip_prefix,
        details=details,
        now=now,
    )


def _checked(
    conn: Connection, account: AccountRow, result: str, now: datetime, ip_prefix: str | None
) -> None:
    record_event(
        conn,
        "garmin.account_checked",
        actor_user_id=account.user_id,
        subject_user_id=account.user_id,
        ip_prefix=ip_prefix,
        details={"garmin_account_id": str(account.garmin_account_id), "result": result},
        now=now,
    )


def _apply_definitive(
    ctx: GarminContext,
    account: AccountRow,
    *,
    status: str,
    error_code: str | None,
    via: str,
    result: str,
    now: datetime,
    ip_prefix: str | None,
    renewed: GarminTokens | None = None,
) -> bool:
    """Aplica un resultado definitivo si la cuenta sigue vinculada (R6); indica si se aplicó."""
    with ctx.engine.begin() as conn:
        values = {
            "status": status,
            "error_code": error_code,
            "last_checked_at": now,
            "updated_at": now,
        }
        if not update_if_active(conn, account.garmin_account_id, values):
            return False
        if renewed is not None:
            save_token(conn, account.garmin_account_id, renewed, ctx.cipher, now, renewed=True)
        if status != "valid":
            _status_change(conn, account, status, via, now, ip_prefix, error_code)
        _checked(conn, account, result, now, ip_prefix)
    return True


def check_account(
    ctx: GarminContext,
    *,
    user_id: UUID,
    account_id: UUID,
    now: datetime,
    ip_prefix: str | None,
) -> CheckOutcome:
    """Comprueba el acceso con Garmin sin descargar datos, como mucho una vez por minuto.

    `last_checked_at` solo se actualiza con un resultado definitivo; un error transitorio no
    cambia nada (FR-017). Lanza `GarminActionFailed` (conflicto) si no se puede comprobar.
    """
    with ctx.engine.begin() as conn:
        account = get_own_account(conn, user_id, account_id)
        if account is None or not account.is_active:
            raise GarminActionFailed(MSG_STATE_NOT_ALLOWED, "conflict")
        if not lease.claim_check(conn, account_id, now, ctx.settings.garmin_check_interval_seconds):
            raise GarminActionFailed(MSG_CHECK_TOO_SOON, "conflict")
        if not lease.acquire(conn, account_id, now, ctx.settings.garmin_request_lease_seconds):
            raise GarminActionFailed(MSG_BUSY, "conflict")
    try:
        try:
            with ctx.engine.connect() as conn:
                tokens = load_tokens(conn, account_id, ctx.cipher)
        except UndecryptableToken:
            applied = _apply_definitive(
                ctx,
                account,
                status="error",
                error_code="token_undecryptable",
                via="token_use",
                result="error",
                now=now,
                ip_prefix=ip_prefix,
            )
            return CheckOutcome(MSG_TOKEN_UNDECRYPTABLE if applied else MSG_CHANGED, False)
        try:
            verified = ctx.client.verify(tokens)
        except TokenRejected:
            applied = _apply_definitive(
                ctx,
                account,
                status="reauth_required",
                error_code=None,
                via="check",
                result="token_rejected",
                now=now,
                ip_prefix=ip_prefix,
            )
            return CheckOutcome(MSG_TOKEN_REJECTED if applied else MSG_CHANGED, False)
        except GarminError as error:
            with ctx.engine.begin() as conn:
                _checked(conn, account, "transient", now, ip_prefix)
            return CheckOutcome(message_for(error), False)
        if verified.identity.profile_id != account.garmin_profile_id:
            applied = _apply_definitive(
                ctx,
                account,
                status="error",
                error_code="identity_mismatch",
                via="check",
                result="error",
                now=now,
                ip_prefix=ip_prefix,
            )
            return CheckOutcome(MSG_IDENTITY_MISMATCH if applied else MSG_CHANGED, False)
        applied = _apply_definitive(
            ctx,
            account,
            status="valid",
            error_code=None,
            via="check",
            result="ok",
            now=now,
            ip_prefix=ip_prefix,
            renewed=verified.renewed_tokens,
        )
        return CheckOutcome(MSG_CHECK_OK, True) if applied else CheckOutcome(MSG_CHANGED, False)
    finally:
        _release(ctx, account_id)


# --- Listado (US2) ------------------------------------------------------------------------

ATTENTION_STATUSES = ("reauth_required", "error")


def list_accounts(conn: Connection, user_id: UUID) -> list[AccountRow]:
    rows = conn.execute(
        select(*_ACCOUNT_COLUMNS)
        .where(_c.user_id == user_id)
        .order_by(_c.created_at, _c.garmin_account_id)
    )
    return [_row(r._mapping) for r in rows]


def accounts_needing_attention(conn: Connection, user_id: UUID) -> list[AccountRow]:
    """Cuentas en "Requiere reautenticación" o "Error", para el aviso de inicio (FR-016a)."""
    return [a for a in list_accounts(conn, user_id) if a.status in ATTENTION_STATUSES]
