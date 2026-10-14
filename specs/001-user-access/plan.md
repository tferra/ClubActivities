# Implementation Plan: Gestión de usuarios y acceso

**Branch**: `001-user-access` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-user-access/spec.md`

## Summary

Primera feature de garmin-hub. Crea la base del proyecto:
- `pyproject` con `uv`, configuración por entorno, `SecretProvider`, logging sin secretos,
  conexión a SQL Server y Alembic con la migración `0001_user_access`.

Sobre esa base implementa el acceso a la aplicación:
- alta solo por invitación ligada a un correo;
- inicio de sesión con sesiones en servidor, CSRF, límite de intentos por correo + origen y por
  origen, y retardo global por correo;
- perfil, administración de usuarios e invitaciones, y restablecimiento con un código del
  administrador;
- borrado del usuario mediante un registro de pasos que ampliarán las features posteriores;
- comandos `db upgrade`, `admin create` y `web serve`.

Enfoque técnico: FastAPI síncrono, SQLAlchemy Core y pyodbc, plantillas Jinja2 con HTMX
vendorizado y una CSP estricta, argon2 para contraseñas y HMAC para códigos, sesiones y
seudónimos (ver [research.md](research.md)).

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**:
- fastapi, uvicorn, jinja2, python-multipart, typer;
- sqlalchemy (Core), pyodbc, alembic, pydantic-settings, argon2-cffi;
- htmx 2.x vendorizado.

**Storage**: SQL Server (schema `gh`, configurable). En esta feature no hay ficheros crudos.

**Testing**:
- pytest:
  - unitarios sin red ni base de datos;
  - `integration` contra `GARMIN_HUB_TEST_DB_URL`, con un schema aleatorio por ejecución;
  - `live` excluido por defecto (no se usa en 001).
- `httpx` para el `TestClient` y `typer.testing.CliRunner` para el CLI.

**Target Platform**:
- Servidor Linux en Docker (feature 011).
- Desarrollo en Windows (PowerShell) y en Linux/WSL.

**Project Type**: aplicación web renderizada en el servidor, con CLI.

**Performance Goals**:
- Páginas con p95 < 300 ms, sin contar la verificación de argon2.
- Inicio de sesión < 1 s.
- Alta completa < 2 min para el usuario (SC-001).

**Constraints**:
- Sin estado en el proceso (sesiones en la base de datos).
- Sin CDN.
- CSP sin `unsafe-inline`.
- Ningún secreto ni dato personal en logs ni en claro en la base de datos.

**Scale/Scope**: unas decenas de usuarios y de 1 a 3 administradores; 6 tablas y unas 12
pantallas sencillas.

Sin NEEDS CLARIFICATION: las decisiones abiertas están resueltas en research.md (R1–R19).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principio | Aplicación en 001 | Estado |
|---|-----------|-------------------|--------|
| I | Datos crudos primero | No se descarga nada de Garmin. El hook de borrado prevé `RawStore` en su contexto para las features posteriores | N/A |
| II | Idempotencia y reanudabilidad | `db upgrade` es idempotente. El borrado es reanudable (`pending_deletion` + pasos idempotentes, R16). El consumo de códigos es atómico (R17). `sync_job` todavía no existe | ✅ |
| III | Respeto a Garmin | Sin acceso a Garmin | N/A |
| IV | Seguridad | argon2 (R4); sesión en servidor con cookie `__Host-` HttpOnly/Secure/SameSite (R8); CSRF en todo POST (R9); límite de intentos (R10); cabeceras (R12); mensajes genéricos; secretos solo por `SecretProvider` (R13); logs filtrados (R14). Fernet entra con los tokens de Garmin | ✅ |
| V | Privacidad y consentimiento | El administrador solo ve datos de cuenta, nunca de entrenamiento ni de salud (FR-004a). La auditoría es de solo inserción, con trigger (R15). Hay borrado propio y por el administrador (R16). La exportación se aplaza a la feature que introduce datos exportables (en 001 no hay datos que exportar más allá del perfil visible en `/cuenta`) | ✅ |
| VI | Autorización centralizada | 001 no expone datos de atleta, así que `can_view` se crea con la feature de clubes y consentimiento. El acceso administrativo pasa por una única dependencia `require_admin`, y `/admin/**` devuelve 404 a quien no es administrador | ✅ |
| VII | Portabilidad | Procesos sin estado; configuración 12 factores; `SecretProvider` es la única interfaz de portabilidad que se introduce ahora | ✅ |
| VIII | Multiplataforma | `pathlib`; prompts de Typer en lugar de `getpass` del shell; Alembic se configura de forma programática; quickstart con equivalentes de PowerShell | ✅ |
| IX | Calidad verificable | Tipado, ruff, pytest con las marcas `integration` y `live`; esquema solo mediante la migración `0001` | ✅ |
| X | Simplicidad | Sin Redis ni librerías CSRF o de límite de intentos; dependencias justificadas (R19); sin abstracciones de repositorio | ✅ |
| XI | Modelo de datos y unidades | UTC `DATETIME2`, UUID estables, correo como atributo | ✅ |
| XII | Idioma | Interfaz y documentación en español; tablas, columnas y código en inglés (confirmado por el propietario, que descartó usar nombres en español) | ✅ |
| XIII | Guiado por especificación | specify → clarify → plan (este documento) → tasks → analyze → implement | ✅ |

**Resultado**: pasa, sin violaciones. Re-evaluación tras la fase 1: sin cambios.

## Project Structure

### Documentation (this feature)

```text
specs/001-user-access/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   ├── http.md
│   └── audit-events.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml           # uv, ruff, pytest (markers integration/live; -m "not live and not integration")
.env.example
src/garmin_hub/
├── __init__.py
├── config.py            # Settings (pydantic-settings), timeouts y límites de FR-002
├── secrets.py           # SecretProvider, EnvSecretProvider, load_secrets, MissingSecretsError
├── keys.py              # derivación de subclaves HMAC (R7)
├── logging_setup.py     # formateador JSON, RedactingFilter, rotación
├── clock.py             # utc_now() (inyectable en servicios)
├── db/
│   ├── engine.py        # create_engine (fast_executemany listo para features de carga)
│   ├── schema.py        # MetaData de SQLAlchemy Core (tablas de data-model.md)
│   └── migrations/      # env.py + versions/0001_user_access.py
├── security/
│   ├── passwords.py     # argon2, política, dummy hash
│   ├── data/common_passwords.txt.gz
│   ├── codes.py         # generación/normalización/HMAC de códigos
│   ├── sessions.py      # crear/resolver/invalidar sesiones
│   ├── csrf.py          # tokens con sesión y anónimos + middleware
│   ├── ratelimit.py     # reglas R10 (función pura de decisión + consultas)
│   └── headers.py       # middleware de cabeceras
├── accounts/
│   ├── users.py         # alta, perfil, contraseña, desactivar/reactivar, último admin
│   ├── invitations.py
│   ├── resets.py
│   ├── deletion.py      # registro de pasos + flujo de borrado (R16)
│   └── audit.py         # record_event con lista blanca de details
├── web/
│   ├── app.py           # create_app(settings, secrets)
│   ├── deps.py          # current_user, require_user, require_admin
│   ├── routes/          # auth.py, signup.py, reset.py, account.py, admin.py
│   ├── templates/       # base.html, login, alta, restablecer, cuenta, admin/*, errores (es)
│   └── static/          # css/app.css, vendor/htmx-2.x.min.js
└── cli/
    └── main.py          # Typer: db upgrade, admin create, web serve

tests/
├── conftest.py          # marcas, fixtures de settings/secretos, clock falso
├── unit/                # passwords, codes, keys, csrf, ratelimit (decisión), redacción, settings, headers
└── integration/         # conftest con schema aleatorio; flujos US1–US8, concurrencia,
                         # inmutabilidad de auditoría, borrado completo, sin-secretos (BD + logs)
```

**Structure Decision**: proyecto único con layout `src/garmin_hub/`.
- **Web**: dentro del paquete, con plantillas y estáticos incluidos como datos del paquete.
- **Dominio** (`accounts/`): usa SQLAlchemy Core directamente, sin capa de repositorio
  (constitución X).
- **Rutas**: solo validan los formularios y llaman a `accounts/` y `security/`.

## Notas para features posteriores

- **Desactivación (FR-026)**: el scheduler y los productores de `sync_job` deben ignorar las cuentas
  Garmin de usuarios con `status != 'active'`, y `can_view` debe denegar si el atleta no está
  `active`. No se crea ningún hook de desactivación; basta con consultar el estado.
- **Borrado**: cada feature que guarde datos de usuario registra su paso con
  `register_deletion_step` y añade un test al borrado completo.
- **Nombres de categoría de consentimiento**: según la constitución XII deben ir en inglés
  (`activities`, `route`, `health`). Hay que alinearlo con la constitución, que hoy dice
  `route_map` y `daily_health`, cuando se especifique esa feature.

## Complexity Tracking

Sin violaciones de la constitución que justificar.
