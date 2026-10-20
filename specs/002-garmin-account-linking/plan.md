# Implementation Plan: Vinculación y gestión de cuentas Garmin

**Branch**: `002-garmin-account-linking` | **Date**: 2026-10-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-garmin-account-linking/spec.md`

## Summary

Los usuarios normales vinculan desde la web una o varias cuentas Garmin Connect propias, con un
alias, el correo, la contraseña y, si Garmin lo pide, el código MFA. También pueden verlas,
reautenticarlas, comprobarlas y desvincularlas conservando o borrando sus datos, siempre después
de aceptar un aviso de datos versionado.

**Qué se guarda y qué no**:
- La contraseña y el correo de Garmin solo viven en memoria durante el login.
- Se guarda el acceso que concede Garmin, cifrado con Fernet y con `key_version`, y el
  `profileId` de Garmin para impedir duplicados.

**Enfoque técnico** (ver [research.md](research.md)):
- Interfaz propia `GarminClient` con una implementación sobre `garminconnect==0.3.17` (su clase de
  bajo nivel `Client`; `garth` está obsoleto) y otra falsa para tests y demo.
- El intento pendiente de MFA se guarda en la memoria del proceso web, porque la librería guarda
  ese estado en una sesión HTTP viva que no se puede serializar. Lo permite la excepción de la
  constitución VII (v1.1.0).
- Unicidad con índices filtrados de SQL Server.
- Candado por cuenta mediante un `UPDATE` condicional.
- Borrado de cuenta reanudable con un registro de pasos que ampliarán las features de datos.
- Comandos nuevos `key generate` y `key reencrypt`.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**:
- las de 001;
- `cryptography` (Fernet);
- `garminconnect==0.3.17`, que trae `curl_cffi`, `requests` y `ua-generator` (R19).

**Storage**:
- SQL Server (schema `gh`), con la migración `0002_garmin_accounts` y 4 tablas nuevas.
- Sin ficheros crudos en esta feature: la descarga llega después.

**Testing**:
- pytest, con unitarios sin red, `integration` con `FakeGarminClient` y `live` (excluido por
  defecto) contra Garmin real (R16).
- La comprobación rápida con `GARMIN_HUB_TEST_DB_URL=sqlite://` cubre la lógica, incluidos los
  índices parciales.
- La concurrencia real lleva la marca `mssql`.

**Target Platform**: la misma que en 001: servidor Linux en Docker, y desarrollo en Windows y en
Linux/WSL.

**Project Type**: aplicación web renderizada en el servidor, con CLI (la misma base que 001).

**Performance Goals**:
- Vincular en menos de 1 minuto (SC-001), dominado por el login de Garmin: entre 2 y 10 s en
  condiciones normales.
- El resto de páginas, como en 001: p95 < 300 ms sin llamadas a Garmin.

**Constraints**:
- Ninguna contraseña, correo de Garmin, código MFA ni acceso en claro en la base de datos, los
  logs, la auditoría ni las respuestas (SC-002).
- Una sola petición en curso por cuenta (constitución III).
- No hay reintentos automáticos del login (spec).
- Un único proceso web mientras el intento MFA viva en memoria (R3).

**Scale/Scope**:
- Decenas de usuarios con hasta 10 cuentas cada uno.
- 4 tablas, unas 8 pantallas o fragmentos y 2 comandos de CLI.

Sin NEEDS CLARIFICATION: las cuestiones técnicas están resueltas en research.md (R1–R19).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principio | Aplicación en 002 | Estado |
|---|-----------|-------------------|--------|
| I | Datos crudos primero | No se descarga nada de Garmin (la comprobación solo verifica el acceso). El registro de pasos de borrado de cuenta prevé los pasos de crudos de las features posteriores | N/A |
| II | Idempotencia y reanudabilidad | La aceptación del aviso es idempotente; `key reencrypt` también. El borrado de cuenta es reanudable (`deleting` + pasos idempotentes, R14). Las transacciones son cortas y las llamadas a Garmin van fuera de ellas (R12). `sync_job` llega con la sincronización | ✅ |
| III | Respeto a Garmin | Una petición en curso por cuenta, garantizada en la base de datos con `request_lease_until` (R6). Una comprobación por minuto. Límite de 5 logins fallidos cada 15 minutos (R9). Backoff con jitter y límite configurable en `verify`. En el login (III, v1.1.0), las estrategias se recorren una a una, con una pausa con jitter entre ellas, corte ante el primer 429 o 403, 45 s como máximo y reintentos configurables (0 por defecto) (R11). La librería solo se importa en `GarminConnectClient`, y un test lo vigila (R1, R2) | ✅ |
| IV | Seguridad | La contraseña de Garmin no tiene campo en ningún esquema ni modelo, y se usa `Client` y no `Garmin`, que la retendría (R1). Accesos con Fernet + `key_version` y rotación (R5). CSRF, sesiones y cabeceras de 001. Mensajes sin detalles técnicos (R10). Secreto nuevo por `SecretProvider`, y el arranque falla si falta (FR-027). Loggers de la librería silenciados y filtrados; test de centinelas en la base de datos y en los logs (R16, R17) | ✅ |
| V | Privacidad y consentimiento | Aviso versionado y auditado antes de vincular (R13). El administrador no tiene ninguna ruta (`require_regular_user` → 404, R15). La vinculación y el resto de acciones se auditan (contracts/audit-events.md). El usuario puede borrar una cuenta Garmin y sus datos (R14). Exportación ampliada. Minimización: el correo de Garmin no se guarda (FR-028a) | ✅ |
| VI | Autorización centralizada | No expone datos de atleta, así que `can_view` llega con clubes y consentimiento. La gestión de cuentas pasa por una única función `get_own_account(user_id, account_id)` con denegación indistinguible (R15). Matriz de tests de propietario, otro usuario, administrador, UUID mal formado e inexistente | ✅ |
| VII | Portabilidad | Configuración 12 factores y `GarminClient` como punto de sustitución. El intento MFA (5 minutos como máximo, sin secretos persistentes) vive en la memoria del proceso web, al amparo de la excepción de VII v1.1.0 para handshakes de autenticación (R3). El despliegue mantiene un único proceso web | ✅ |
| VIII | Multiplataforma | Sin dependencias de shell. `curl_cffi` publica wheels para Windows, Linux y macOS; se comprueba con `uv sync` en PowerShell (T001). Quickstart con equivalentes en PowerShell | ✅ |
| IX | Calidad verificable | Tipos, ruff y pytest. Migración `0002` con prueba arriba y abajo. Unitarios sin red con `FakeGarminClient`; `live` separado y excluido | ✅ |
| X | Simplicidad | Dos dependencias justificadas (R19). Sin colas ni cachés. El registro de MFA es una clase con un diccionario y un candado. No hay repositorios | ✅ |
| XI | Modelo de datos y unidades | UTC `DATETIME2(3)`. `garmin_account_id` estable, independiente del alias y del correo (FR-005) | ✅ |
| XII | Idioma | Interfaz y documentación en español; tablas, columnas y código en inglés | ✅ |
| XIII | Guiado por especificación | specify → clarify (5 preguntas) → plan → tasks → analyze → implement | ✅ |

**Resultado**: pasa, sin violaciones, con la constitución v1.1.0. La enmienda de III y VII se
hizo el 2026-10-20 a raíz de `/speckit-analyze`, hallazgos C1 y C2. Re-evaluación tras la fase 1:
sin cambios. El modelo de datos y los contratos no añaden más estado en el proceso ni otras
dependencias.

## Project Structure

### Documentation (this feature)

```text
specs/002-garmin-account-linking/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── http.md
│   ├── cli.md
│   ├── audit-events.md
│   └── garmin-client.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml                    # + cryptography, garminconnect==0.3.17
.env.example                      # + GARMIN_HUB_MASTER_KEYS, GARMIN_HUB_GARMIN_*
src/garmin_hub/
├── config.py                     # + ajustes GARMIN_HUB_GARMIN_* (data-model.md) y validación fake/prod
├── secrets.py                    # + GARMIN_HUB_MASTER_KEYS obligatorio y validado
├── logging_setup.py              # + loggers garminconnect/curl_cffi en ERROR y filtrados (R17)
├── security/
│   └── token_cipher.py           # TokenCipher: análisis de claves, cifrar/descifrar con versión (R5)
├── garmin/
│   ├── client.py                 # Protocol GarminClient, tipos y errores (contracts/garmin-client.md)
│   ├── garminconnect_client.py   # única importación de garminconnect (R1)
│   ├── fake.py                   # FakeGarminClient
│   ├── pending.py                # PendingLoginRegistry en memoria (R3)
│   └── retry.py                  # backoff con jitter para verify (R11)
├── garmin_accounts/
│   ├── accounts.py               # vincular, recuperar, reautenticar, comprobar, desvincular, listar, get_own_account
│   ├── notice.py                 # NOTICE_VERSION, aceptación
│   ├── ratelimit.py              # garmin_login_failure (R9)
│   ├── lease.py                  # candado por cuenta y reclamación de la comprobación (R6)
│   ├── errors.py                 # mapeo GarminError → mensaje en español y efecto (R10)
│   ├── deletion.py               # registro de pasos por cuenta + paso de usuario (R14)
│   └── export.py                 # secciones de exportación
├── accounts/audit.py             # + eventos garmin.* en ALLOWED_DETAILS
├── db/
│   ├── schema.py                 # + tablas de data-model.md
│   └── migrations/versions/0002_garmin_accounts.py
├── web/
│   ├── app.py                    # + app.state.garmin_client, pending_logins y token_cipher; router nuevo
│   ├── deps.py                   # + require_regular_user
│   ├── routes/garmin_accounts.py # rutas de contracts/http.md
│   ├── routes/account.py         # home: avisos (FR-016a, FR-012)
│   └── templates/
│       ├── base.html, home.html  # menú y avisos
│       └── garmin/               # list, _row, notice_v1, link, mfa, reauth, unlink, delete_data
└── cli/main.py                   # + key generate, key reencrypt

tests/
├── unit/        # token_cipher, keys env, error mapping, pending registry, alias, retry, import guard
├── integration/ # flujos US1–US7, autorización, unicidad/recuperación, lease, límites, borrado
│                # reanudable, borrado de usuario, exportación, migración 0002, auditoría, SC-002
└── live/        # test_garminconnect_client.py (marca live)
```

**Structure Decision**: se mantiene el proyecto único `src/garmin_hub/`.
- `garmin/` contiene todo lo que habla con Garmin (constitución III).
- `garmin_accounts/` contiene el dominio de esta feature, con SQLAlchemy Core directo, como
  `accounts/` en 001.
- Las rutas solo validan formularios y llaman al dominio.

## Notas para features posteriores

- **Sincronización**:
  - Debe pedir cada petición con el candado `request_lease_until` (R6).
  - Debe tratar `TokenRejected` con la transición a `reauth_required`, usando
    `via: "sync"` en la auditoría.
  - Debe ignorar las cuentas que no estén en `valid` y las de usuarios no `active`.
  - Debe rellenar `last_sync_at`.
  - Al usar o renovar un acceso, debe recifrarlo con la clave vigente.
- **Datos y crudos**:
  - Cada feature que guarde datos de una cuenta registra un paso con
    `register_account_deletion_step` (orden < 1000), y otro de exportación si procede.
  - `DeletionContext` añadirá `raw_store`.
- **Clubes y consentimiento**: `can_view` debe tratar los datos de cuentas `unlinked` igual que los
  de las vinculadas (FR-023), y denegar los de `deleting`.
- **Despliegue (011)**: un solo proceso web, o afinidad de sesión, mientras el intento MFA viva en
  memoria (R3).
- **Assumption nueva** (R8): el máximo de 10 cuentas cuenta solo las vinculadas (`valid`,
  `reauth_required` y `error`), no las desvinculadas con datos conservados.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

No hay violaciones de la constitución v1.1.0. El estado MFA en memoria (R3) usa la excepción
explícita de VII, y el control del login (R11) aplica la regla nueva de III.
