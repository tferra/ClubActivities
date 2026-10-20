# garmin-hub

Aplicación web multiusuario para descargar y visualizar los datos de cuentas de Garmin Connect
(actividades, salud diaria) y compartirlos con entrenadores de un club, siempre con el
consentimiento explícito del atleta.

Esta primera versión (feature `001-user-access`) incluye la base del proyecto y la gestión de
usuarios y acceso:

- alta solo por invitación ligada a un correo;
- inicio y cierre de sesión con límites de intentos;
- perfil, cambio de contraseña y exportación de los datos propios;
- administración de usuarios e invitaciones;
- borrado del propio usuario;
- restablecimiento de contraseña con un código que genera el administrador.

La vinculación de cuentas Garmin, los clubes y los entrenadores llegan en features posteriores.

## Requisitos

- Python 3.12 o superior y [uv](https://docs.astral.sh/uv/).
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/microsoft-odbc-driver-for-sql-server).
- Una base de datos SQL Server (la aporta el propietario). Para los tests de integración, una
  base desechable.
- Para usar la web en desarrollo, Chrome, Edge o Firefox: las cookies son siempre `Secure` y
  esos navegadores las aceptan en `http://localhost`.

## Instalación

bash (Linux, WSL, macOS):

```bash
uv sync
cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

PowerShell (Windows):

```powershell
uv sync
Copy-Item .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Pega el valor generado en `GARMIN_HUB_SESSION_SECRET` y rellena `GARMIN_HUB_DB_URL` en `.env`.

## Configuración

Todas las variables están documentadas en [`.env.example`](.env.example).

- Los **secretos** (`GARMIN_HUB_DB_URL`, `GARMIN_HUB_SESSION_SECRET`) solo llegan por variables de
  entorno a través de `SecretProvider`; nunca se guardan en el repositorio.
- `.env` solo se lee si `GARMIN_HUB_ENV=dev`, y las variables del entorno real tienen prioridad.
- `GARMIN_HUB_PUBLIC_URL` es obligatoria (`http://localhost:8000` en desarrollo). Abre la web
  exactamente en esa URL.
- Si falta un secreto o la configuración obligatoria, los comandos terminan con el código 2 y
  nombran lo que falta, sin mostrar ningún valor.

## Comandos

```bash
uv run garmin-hub db upgrade                                   # crea o actualiza el esquema (idempotente)
uv run garmin-hub admin create --email admin@club.test --name Admin   # pide la contraseña sin eco
uv run garmin-hub web serve                                    # http://localhost:8000
```

| Código de salida | Significado |
|------------------|-------------|
| 0 | Éxito |
| 1 | Error de validación (correo ya registrado, contraseña no válida…) |
| 2 | Faltan secretos o configuración obligatoria |
| 3 | No hay conexión con la base de datos o el esquema no está actualizado |

Los administradores solo se crean con `admin create`; ninguna acción de la web otorga ese rol.

## Calidad

```bash
uv run ruff check
uv run ruff format --check
uv run pytest                     # unitarios: sin red ni base de datos
```

Tests de integración contra SQL Server desechable (cada ejecución crea y borra un schema
`gh_t_<hex>`):

```bash
GARMIN_HUB_TEST_DB_URL="mssql+pyodbc://..." uv run pytest -m integration
```

```powershell
$env:GARMIN_HUB_TEST_DB_URL="mssql+pyodbc://..."; uv run pytest -m integration
```

Con `GARMIN_HUB_TEST_DB_URL=sqlite://` se puede hacer una comprobación rápida local; los tests
que dependen de SQL Server (migraciones, trigger de auditoría, concurrencia) se omiten. La
validación de referencia es siempre contra SQL Server.

## Cómo se desarrolla

El proyecto sigue [Spec Kit](https://github.com/github/spec-kit) y su
[constitución](.specify/memory/constitution.md): cada feature pasa por `/speckit-specify` →
`/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` →
`/speckit-implement`. La documentación de cada feature está en `specs/`; la de esta versión, en
[`specs/001-user-access/`](specs/001-user-access/) (con una guía de validación en
[`quickstart.md`](specs/001-user-access/quickstart.md)).

La interfaz y la documentación están en español; el código, los nombres de tablas y columnas,
los logs y los commits, en inglés.
