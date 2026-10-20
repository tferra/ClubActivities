"""CLI `garmin-hub` (contracts/cli.md)."""

import os
from dataclasses import dataclass
from typing import Annotated

import typer

from garmin_hub.config import MissingConfigError, Settings, load_env_file, load_settings
from garmin_hub.logging_setup import configure_logging
from garmin_hub.secrets import EnvSecretProvider, MissingSecretsError, Secrets, load_secrets

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_CONFIG = 2
EXIT_DATABASE = 3

app = typer.Typer(
    help="garmin-hub: administración desde la línea de comandos.", no_args_is_help=True
)
db_app = typer.Typer(help="Base de datos.", no_args_is_help=True)
admin_app = typer.Typer(help="Administradores.", no_args_is_help=True)
web_app = typer.Typer(help="Servidor web.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(admin_app, name="admin")
app.add_typer(web_app, name="web")


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    secrets: Secrets


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(code)


def bootstrap() -> Runtime:
    """Carga configuración y secretos; convierte los errores en la salida 2."""
    env_file = load_env_file()
    try:
        settings = load_settings(env_file)
    except MissingConfigError as exc:
        raise _fail(exc.message, EXIT_CONFIG) from None
    try:
        secrets = load_secrets(EnvSecretProvider(fallback=env_file))
    except MissingSecretsError as exc:
        typer.echo(f"Error: {exc.message}", err=True)
        typer.echo("Defínelos como variables de entorno (ver .env.example).", err=True)
        raise typer.Exit(EXIT_CONFIG) from None
    configure_logging(settings)
    return Runtime(settings=settings, secrets=secrets)


def _engine_at_head(runtime: Runtime):  # noqa: ANN202
    from sqlalchemy.exc import SQLAlchemyError

    from garmin_hub.db.engine import check_schema_at_head, create_engine_from

    try:
        engine = create_engine_from(runtime.secrets, runtime.settings)
        at_head = check_schema_at_head(engine, runtime.settings)
    except (SQLAlchemyError, ImportError):
        raise _fail("no se puede conectar con la base de datos.", EXIT_DATABASE) from None
    if not at_head:
        raise _fail(
            "el esquema de la base de datos no está actualizado; ejecuta `garmin-hub db upgrade`.",
            EXIT_DATABASE,
        )
    return engine


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Option(help="Revisión destino.")] = "head",
) -> None:
    """Aplica las migraciones de Alembic (idempotente)."""
    from sqlalchemy.exc import SQLAlchemyError

    from garmin_hub.db.engine import create_engine_from
    from garmin_hub.db.migrate import run_upgrade

    runtime = bootstrap()
    try:
        engine = create_engine_from(runtime.secrets, runtime.settings)
        current = run_upgrade(engine, runtime.settings.db_schema, revision)
    except (SQLAlchemyError, ImportError):
        raise _fail("no se puede conectar con la base de datos.", EXIT_DATABASE) from None
    typer.echo(f"Base de datos actualizada a la revisión {current}.")


@admin_app.command("create")
def admin_create(
    email: Annotated[str, typer.Option(help="Correo del administrador.")],
    name: Annotated[str, typer.Option(help="Nombre visible.")],
) -> None:
    """Crea un administrador. La contraseña se pide sin eco y con confirmación."""
    from garmin_hub.accounts.users import ValidationFailed, check_new_admin, create_admin
    from garmin_hub.clock import utc_now

    runtime = bootstrap()
    engine = _engine_at_head(runtime)
    try:
        with engine.begin() as conn:
            check_new_admin(conn, email=email, display_name=name, now=utc_now())
        password = typer.prompt(
            "Contraseña", hide_input=True, confirmation_prompt="Repite la contraseña"
        )
        with engine.begin() as conn:
            user_id = create_admin(
                conn, email=email, display_name=name, password=password, now=utc_now()
            )
    except ValidationFailed as exc:
        raise _fail(exc.message, EXIT_VALIDATION) from None
    typer.echo(f"Administrador creado: {user_id}")


@web_app.command("serve")
def web_serve(
    host: Annotated[str, typer.Option(help="Interfaz de escucha.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Puerto.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Recarga automática (solo dev).")] = False,
) -> None:
    """Arranca el servidor web."""
    import uvicorn

    runtime = bootstrap()
    if reload and runtime.settings.env != "dev":
        raise _fail("--reload solo está permitido con GARMIN_HUB_ENV=dev.", EXIT_CONFIG)
    engine = _engine_at_head(runtime)
    options = {
        "host": host,
        "port": port,
        "proxy_headers": True,
        "forwarded_allow_ips": runtime.settings.trusted_proxies,
        "access_log": False,
        "log_config": None,
    }
    if reload:
        uvicorn.run("garmin_hub.web.app:app_from_env", factory=True, reload=True, **options)
    else:
        from garmin_hub.web.app import create_app

        uvicorn.run(create_app(runtime.settings, runtime.secrets, engine=engine), **options)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
