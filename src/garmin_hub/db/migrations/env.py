"""Entorno de Alembic: recibe la conexión y el schema desde `garmin_hub.db.migrate`."""

from alembic import context
from sqlalchemy import text

connection = context.config.attributes.get("connection")
schema = context.config.attributes.get("schema", "gh")

if context.is_offline_mode():
    # Solo para revisar el SQL generado (render_sql); nunca se usa para migrar.
    context.configure(dialect_name="mssql", version_table_schema=schema, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    if connection is None:
        raise RuntimeError("Usa garmin_hub.db.migrate (garmin-hub db upgrade) para migrar.")
    connection.execute(text(f"IF SCHEMA_ID(N'{schema}') IS NULL EXEC(N'CREATE SCHEMA [{schema}]')"))
    context.configure(connection=connection, target_metadata=None, version_table_schema=schema)
    with context.begin_transaction():
        context.run_migrations()
