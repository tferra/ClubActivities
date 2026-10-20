"""Alembic con configuración programática (sin `alembic.ini`), research R2."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _config(connection: Connection | None = None, schema: str = "gh") -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    config.attributes["schema"] = schema
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(_config()).get_current_head()


def current_revision(conn: Connection, schema: str) -> str | None:
    context = MigrationContext.configure(conn, opts={"version_table_schema": schema})
    return context.get_current_revision()


def run_upgrade(engine: Engine, schema: str, revision: str = "head") -> str | None:
    with engine.begin() as conn:
        command.upgrade(_config(conn, schema), revision)
        return current_revision(conn, schema)


def run_downgrade(engine: Engine, schema: str, revision: str = "base") -> None:
    with engine.begin() as conn:
        command.downgrade(_config(conn, schema), revision)


def render_sql(schema: str, revision: str = "head", downgrade: bool = False) -> str:
    """Devuelve el SQL de SQL Server de las migraciones, sin conectarse (revisión manual)."""
    import io

    buffer = io.StringIO()
    config = _config(None, schema)
    config.output_buffer = buffer
    if downgrade:
        command.downgrade(config, f"{revision}:base", sql=True)
    else:
        command.upgrade(config, revision, sql=True)
    return buffer.getvalue()
