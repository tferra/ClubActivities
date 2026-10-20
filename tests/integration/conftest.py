"""Fixtures de integración contra SQL Server desechable (`GARMIN_HUB_TEST_DB_URL`).

Cada ejecución crea un schema aleatorio `gh_t_<hex>`, aplica las migraciones y lo elimina al
terminar. Con una URL `sqlite://` se puede hacer una comprobación rápida local (sin trigger,
índices de SQL Server ni concurrencia real); los tests marcados `mssql` se omiten en ese caso.
La validación oficial es siempre contra SQL Server.
"""

import json
import logging
import os
import secrets as std_secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, insert, select, text
from sqlalchemy.pool import StaticPool

from garmin_hub.db.engine import with_schema
from garmin_hub.db.migrate import run_downgrade, run_upgrade
from garmin_hub.db.schema import (
    app_user,
    audit_event,
    data_notice_acceptance,
    garmin_account,
    metadata,
)
from garmin_hub.garmin.client import GarminTokens
from garmin_hub.garmin.fake import FakeGarminClient
from garmin_hub.garmin_accounts import notice
from garmin_hub.garmin_accounts.accounts import save_token
from garmin_hub.logging_setup import JsonFormatter, RedactingFilter
from garmin_hub.security import passwords
from garmin_hub.security.csrf import ANON_COOKIE, anon_token, new_anon_pair, session_token
from garmin_hub.security.sessions import COOKIE_NAME, create_session
from garmin_hub.web.app import create_app

DEFAULT_PASSWORD = "cielo-tranquilo-sobre-el-mar"
TEST_IP = "203.0.113.57"
TABLES_CHILD_FIRST = [
    "garmin_token",
    "garmin_account",
    "data_notice_acceptance",
    "garmin_login_failure",
    "user_session",
    "password_reset_code",
    "invitation",
    "login_attempt",
    "app_user",
]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    url = os.environ.get("GARMIN_HUB_TEST_DB_URL")
    for item in items:
        if "integration" not in item.keywords:
            continue
        if not url:
            item.add_marker(pytest.mark.skip(reason="GARMIN_HUB_TEST_DB_URL no definida"))
        elif "mssql" in item.keywords and not url.startswith("mssql"):
            item.add_marker(pytest.mark.skip(reason="requiere SQL Server"))


@pytest.fixture(scope="session")
def db_schema() -> str:
    return f"gh_t_{std_secrets.token_hex(4)}"


@pytest.fixture(scope="session")
def raw_engine(db_schema: str) -> Iterator[Engine]:
    url = os.environ["GARMIN_HUB_TEST_DB_URL"]
    if url.startswith("sqlite"):
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )

        @event.listens_for(engine, "connect")
        def _attach(dbapi_conn: Any, _record: Any) -> None:
            dbapi_conn.execute(f"ATTACH DATABASE ':memory:' AS {db_schema}")

        metadata.create_all(with_schema(engine, db_schema))
        yield engine
        engine.dispose()
        return
    engine = create_engine(url, pool_pre_ping=True)
    run_upgrade(engine, db_schema)
    yield engine
    run_downgrade(engine, db_schema)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS [{db_schema}].[alembic_version]"))
        conn.execute(text(f"DROP SCHEMA [{db_schema}]"))
    engine.dispose()


@pytest.fixture
def engine(raw_engine: Engine, db_schema: str) -> Iterator[Engine]:
    """Engine con el schema de test; vacía las tablas al terminar cada test."""
    engine = with_schema(raw_engine, db_schema)
    yield engine
    with engine.begin() as conn:
        is_mssql = conn.dialect.name == "mssql"
        if is_mssql:
            conn.execute(
                text(
                    f"DISABLE TRIGGER [{db_schema}].[TR_audit_event_immutable] "
                    f"ON [{db_schema}].[audit_event]"
                )
            )
        for name in ["audit_event", *TABLES_CHILD_FIRST]:
            conn.execute(metadata.tables[name].delete())
        if is_mssql:
            conn.execute(
                text(
                    f"ENABLE TRIGGER [{db_schema}].[TR_audit_event_immutable] "
                    f"ON [{db_schema}].[audit_event]"
                )
            )


@pytest.fixture
def fake_garmin() -> FakeGarminClient:
    return FakeGarminClient()


@pytest.fixture
def app(settings, secrets, engine, clock, fake_sleep, fake_garmin):
    return create_app(
        settings, secrets, engine=engine, clock=clock, sleep=fake_sleep, garmin_client=fake_garmin
    )


@pytest.fixture
def pending_logins(app):
    return app.state.pending_logins


@pytest.fixture
def accept_notice(engine, clock):
    def do_accept(user_id: uuid.UUID, version: int | None = None) -> None:
        with engine.begin() as conn:
            conn.execute(
                insert(data_notice_acceptance).values(
                    user_id=user_id,
                    notice_version=version or notice.current_version(),
                    accepted_at=clock(),
                )
            )

    return do_accept


@pytest.fixture
def make_garmin_account(engine, clock, app):
    """Inserta una cuenta Garmin directamente (sin el servicio de US1) y devuelve su id."""
    counter = iter(range(1, 10_000))

    def factory(
        user_id: uuid.UUID,
        *,
        alias: str | None = None,
        profile_id: int | None = None,
        status: str = "valid",
        with_token: bool = True,
        error_code: str | None = None,
        tokens: bytes | None = None,
    ) -> uuid.UUID:
        n = next(counter)
        alias = alias or f"Cuenta {n}"
        profile_id = profile_id if profile_id is not None else 100 + n
        if status == "error" and error_code is None:
            error_code = "identity_mismatch"
        now = clock()
        account_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                insert(garmin_account).values(
                    garmin_account_id=account_id,
                    user_id=user_id,
                    alias=alias,
                    alias_key=alias.strip().casefold(),
                    garmin_profile_id=profile_id,
                    status=status,
                    error_code=error_code,
                    linked_at=now,
                    last_login_at=now,
                    unlinked_at=now if status == "unlinked" else None,
                    deletion_requested_at=now if status == "deleting" else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            if with_token and status in ("valid", "reauth_required", "error"):
                value = tokens or json.dumps({"fake": profile_id, "rev": 0}).encode()
                save_token(conn, account_id, GarminTokens(value), app.state.token_cipher, now)
        return account_id

    return factory


@pytest.fixture
def make_client(app):
    def factory(ip: str = TEST_IP) -> TestClient:
        return TestClient(app, base_url="https://testserver", client=(ip, 50000))

    return factory


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@dataclass
class TestUser:
    user_id: uuid.UUID
    email: str
    display_name: str
    password: str
    role: str


@pytest.fixture
def make_user(engine, clock):
    counter = iter(range(1, 10_000))

    def factory(
        role: str = "user",
        status: str = "active",
        password: str = DEFAULT_PASSWORD,
        email: str | None = None,
        display_name: str | None = None,
    ) -> TestUser:
        n = next(counter)
        email = email or f"persona{n}@club.test"
        display_name = display_name or f"Persona {n}"
        user_id = uuid.uuid4()
        now = clock()
        with engine.begin() as conn:
            conn.execute(
                insert(app_user).values(
                    user_id=user_id,
                    email=email,
                    display_name=display_name,
                    password_hash=passwords.hash_password(password),
                    role=role,
                    status=status,
                    created_at=now,
                    updated_at=now,
                    password_changed_at=now,
                )
            )
        return TestUser(user_id, email, display_name, password, role)

    return factory


@pytest.fixture
def login_as(engine, keys, settings, clock):
    def do_login(client: TestClient, user: TestUser) -> str:
        with engine.begin() as conn:
            raw_id = create_session(conn, user.user_id, keys, settings, clock())
        client.cookies.set(COOKIE_NAME, raw_id)
        return raw_id

    return do_login


@pytest.fixture
def csrf_for(keys):
    def token(client: TestClient) -> str:
        raw_id = client.cookies.get(COOKIE_NAME)
        if raw_id:
            return session_token(keys, raw_id)
        nonce = client.cookies.get(ANON_COOKIE)
        if not nonce:
            nonce, _ = new_anon_pair(keys)
            client.cookies.set(ANON_COOKIE, nonce)
        return anon_token(keys, nonce)

    return token


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.addFilter(RedactingFilter())
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def captured_logs() -> Iterator[list[str]]:
    handler = _ListHandler()
    logger = logging.getLogger("garmin_hub")
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield handler.lines
    logger.removeHandler(handler)
    logger.setLevel(old_level)


@pytest.fixture
def audit_rows(engine):
    def rows(event_type: str | None = None) -> list[dict[str, Any]]:
        stmt = select(audit_event).order_by(audit_event.c.audit_id)
        if event_type is not None:
            stmt = stmt.where(audit_event.c.event_type == event_type)
        with engine.connect() as conn:
            result = [dict(r._mapping) for r in conn.execute(stmt)]
        for row in result:
            row["details"] = json.loads(row["details"]) if row["details"] else {}
        return result

    return rows


@pytest.fixture
def make_invitation(engine, keys, clock):
    """Inserta una invitación directamente (sin el servicio de US2) y devuelve su código."""
    from datetime import timedelta

    from garmin_hub.db.schema import invitation
    from garmin_hub.security.codes import code_hash, generate_code

    def factory(email: str = "ana@club.test", status: str = "pending", ttl_days: int = 7) -> str:
        code = generate_code()
        with engine.begin() as conn:
            conn.execute(
                insert(invitation).values(
                    invitation_id=uuid.uuid4(),
                    code_hash=code_hash(keys, code),
                    email=email,
                    status=status,
                    created_at=clock(),
                    expires_at=clock() + timedelta(days=ttl_days),
                )
            )
        return code

    return factory


@pytest.fixture
def form_post(csrf_for):
    """POST de formulario con el token CSRF de la sesión del cliente, sin seguir redirecciones."""

    def post(client: TestClient, path: str, data: dict[str, Any] | None = None, **kwargs: Any):
        return client.post(
            path,
            data={**(data or {}), "csrf_token": csrf_for(client)},
            follow_redirects=False,
            **kwargs,
        )

    return post


@pytest.fixture
def garmin_user(client, make_user, login_as, accept_notice) -> TestUser:
    """Usuario normal con el aviso de datos aceptado y sesión iniciada en `client`."""
    user = make_user()
    accept_notice(user.user_id)
    login_as(client, user)
    return user


@pytest.fixture
def garmin_rows(engine):
    def rows(user_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        stmt = select(garmin_account).order_by(garmin_account.c.created_at)
        if user_id is not None:
            stmt = stmt.where(garmin_account.c.user_id == user_id)
        with engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(stmt)]

    return rows


@pytest.fixture
def garmin_ctx(app):
    """Dependencias del dominio de cuentas Garmin, las mismas que usan las rutas."""
    from garmin_hub.garmin_accounts.accounts import GarminContext

    state = app.state
    return GarminContext(
        engine=state.engine,
        client=state.garmin_client,
        registry=state.pending_logins,
        cipher=state.token_cipher,
        settings=state.settings,
    )
