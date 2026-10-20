"""Engine de SQL Server (research R1)."""

from sqlalchemy import Engine, create_engine

from garmin_hub.config import Settings
from garmin_hub.secrets import Secrets


def create_engine_from(secrets: Secrets, settings: Settings) -> Engine:
    engine = create_engine(
        secrets.db_url,
        pool_pre_ping=True,
        fast_executemany=True,
    )
    return with_schema(engine, settings.db_schema)


def with_schema(engine: Engine, schema: str) -> Engine:
    """Traduce las tablas sin schema de `db.schema` al schema configurado."""
    return engine.execution_options(schema_translate_map={None: schema})


def check_schema_at_head(engine: Engine, settings: Settings) -> bool:
    """Indica si la revisión de Alembic del schema coincide con `head`."""
    from garmin_hub.db.migrate import current_revision, head_revision

    with engine.connect() as conn:
        return current_revision(conn, settings.db_schema) == head_revision()
