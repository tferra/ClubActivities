---

description: "Lista de tareas de la feature 001: gestión de usuarios y acceso"
---

# Tasks: Gestión de usuarios y acceso

**Input**: documentos de diseño de `/specs/001-user-access/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (cli.md, http.md, audit-events.md), quickstart.md

**Tests**: los pide el propietario y la constitución (IX y XIII). En cada historia, los tests se escriben primero y deben fallar antes de implementar.
- Unitarios en `tests/unit/`: sin red ni base de datos y con fixtures sintéticas.
- Integración en `tests/integration/` con la marca `integration`: contra SQL Server desechable (`GARMIN_HUB_TEST_DB_URL`) con un schema aleatorio por ejecución.

**Organization**: hay una fase por historia de usuario, en el orden de prioridad de la spec (US1–US4 son P1, US5–US7 son P2 y US8 es P3). Gracias a las fixtures `make_user` y `login_as` de la fase 2, cada historia se prueba sin depender de las demás.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede hacer en paralelo (ficheros distintos y sin dependencias pendientes)
- **[Story]**: historia de usuario a la que pertenece (US1…US8)
- Las rutas son relativas a la raíz del repositorio (`src/garmin_hub/`, `tests/`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: inicializar el proyecto. Se hace una sola vez porque es la primera feature.

- [ ] T001 Crear el esqueleto de paquetes según plan.md: `src/garmin_hub/__init__.py` y los `__init__.py` vacíos de `db/`, `db/migrations/`, `db/migrations/versions/`, `security/`, `accounts/`, `web/`, `web/routes/` y `cli/`; las carpetas `src/garmin_hub/web/templates/`, `src/garmin_hub/web/static/css/`, `src/garmin_hub/web/static/vendor/` y `src/garmin_hub/security/data/`; y `tests/__init__.py`, `tests/unit/__init__.py` y `tests/integration/__init__.py`.
- [ ] T002 Crear `pyproject.toml` (proyecto `garmin-hub`, `requires-python = ">=3.12"`, build backend `hatchling` con layout `src/`) con:
  - **Dependencias**: fastapi, uvicorn, jinja2, python-multipart, typer, sqlalchemy>=2, pyodbc, alembic, pydantic-settings, python-dotenv, anyio y argon2-cffi (research R19).
  - **Grupo `dev`**: pytest, ruff y httpx.
  - **Script**: `garmin-hub = "garmin_hub.cli.main:app"`.
  - **Datos del paquete**: incluir `web/templates/**`, `web/static/**` y `security/data/*.gz`.

  Después, generar `uv.lock` con `uv sync`.
- [ ] T003 [P] Configurar ruff en `pyproject.toml`: `[tool.ruff]` con `line-length = 100` y `target-version = "py312"`, y `[tool.ruff.lint] select = ["E","F","W","I","UP","B","S","SIM","RUF","ANN"]` con `ignore = ["ANN401"]`, para exigir tipado en el código público (constitución IX). En `per-file-ignores`, ignorar `S101` y `ANN` en `tests/**` y `ANN` en `src/garmin_hub/db/migrations/**`.
- [ ] T004 [P] Configurar pytest en `pyproject.toml`:
  - `testpaths = ["tests"]` y `pythonpath = ["src"]`;
  - `markers`: `integration` (requiere `GARMIN_HUB_TEST_DB_URL`) y `live` (Garmin real);
  - `addopts = "-m 'not live and not integration' --strict-markers"`.
- [ ] T005 [P] Ampliar `.gitignore` con `.env` y `.env.*` salvo `.env.example` (ya están), `logs/`, `data/raw/` y `*.log`, y comprobar que `uv.lock` **no** queda ignorado.
- [ ] T006 [P] Crear `.env.example` con todas las variables de research R13 y data-model.md, cada una con un comentario en español, sin valores secretos reales:
  - **Secretos**: `GARMIN_HUB_DB_URL` y `GARMIN_HUB_SESSION_SECRET`.
  - **Secretos futuros, comentados**: `# GARMIN_HUB_MASTER_KEYS=` y `# GARMIN_HUB_RAW_DIR=`, con el comentario "obligatoria desde la feature de vinculación de cuentas Garmin" (research R13).
  - **Configuración general**: `GARMIN_HUB_ENV`, `GARMIN_HUB_PUBLIC_URL` (obligatoria; `http://localhost:8000` en desarrollo), `GARMIN_HUB_DB_SCHEMA`, `GARMIN_HUB_TRUSTED_PROXIES`, `GARMIN_HUB_LOG_DIR` y `GARMIN_HUB_LOG_LEVEL`.
  - **Tiempos y límites de FR-002**: `GARMIN_HUB_INVITE_TTL_DAYS=7`, `GARMIN_HUB_RESET_TTL_HOURS=24`, `GARMIN_HUB_SESSION_IDLE_MINUTES=30`, `GARMIN_HUB_SESSION_MAX_HOURS=12`, `GARMIN_HUB_LOGIN_PAIR_MAX_FAILURES=5`, `GARMIN_HUB_LOGIN_PAIR_WINDOW_MINUTES=15`, `GARMIN_HUB_LOGIN_IP_MAX_FAILURES=20`, `GARMIN_HUB_LOGIN_IP_WINDOW_MINUTES=15`, `GARMIN_HUB_LOGIN_EMAIL_SOFT_LIMIT=50`, `GARMIN_HUB_LOGIN_EMAIL_SOFT_WINDOW_MINUTES=60` y `GARMIN_HUB_LOGIN_EMAIL_MAX_DELAY_SECONDS=10`.
- [ ] T007 [P] Vendorizar htmx 2.0.4 en `src/garmin_hub/web/static/vendor/htmx-2.0.4.min.js`, con un `src/garmin_hub/web/static/vendor/VERSIONS.txt` que anote la versión, la URL de origen y el SHA-256.
- [ ] T008 [P] Generar `src/garmin_hub/security/data/common_passwords.txt.gz`:
  - **Origen**: lista "top 1M" de SecLists (licencia MIT).
  - **Contenido**: solo las entradas de 12 o más caracteres, en minúsculas y sin duplicados (research R5).
  - **Licencia**: añadir `src/garmin_hub/security/data/LICENSE-SecLists.txt`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: configuración, secretos, logging, base de datos con la migración 0001, seguridad común, auditoría, app web base, CLI base y fixtures de test.

**⚠️ CRITICAL**: no se puede empezar ninguna historia hasta completar esta fase.

### Tests fundacionales (escribir primero; deben fallar)

- [ ] T009 [P] Test unitario de secretos y configuración en `tests/unit/test_secrets_config.py`:
  - `load_secrets` con un `SecretProvider` falso al que le faltan `GARMIN_HUB_DB_URL` y `GARMIN_HUB_SESSION_SECRET` lanza `MissingSecretsError`, cuyo mensaje en español nombra ambas variables y no contiene ningún valor;
  - un `GARMIN_HUB_SESSION_SECRET` de menos de 32 bytes se rechaza;
  - `Settings` aplica los valores por defecto de FR-002, y un valor distinto en el entorno (por ejemplo `GARMIN_HUB_INVITE_TTL_DAYS=3`) lo sustituye;
  - sin `GARMIN_HUB_PUBLIC_URL`, o con un valor que no es una URL http(s), se lanza `MissingConfigError` con el mensaje en español que la nombra;
  - `load_env_file` (con un `.env` sintético en `tmp_path`) solo devuelve valores si `GARMIN_HUB_ENV=dev` está en el entorno real o en el propio fichero; con `GARMIN_HUB_ENV=prod` en el entorno devuelve un mapa vacío;
  - `EnvSecretProvider(fallback=...)` devuelve un secreto definido solo en `.env`, y el del entorno real tiene prioridad sobre el de `.env` (R13).
- [ ] T010 [P] Test unitario de derivación de claves en `tests/unit/test_keys.py`: las subclaves `session-id`, `csrf`, `code`, `email-rl`, `ip-rl` y `anon-csrf` son distintas entre sí, son deterministas para un mismo secreto y cambian si cambia el secreto (R7).
- [ ] T011 [P] Test unitario del filtro de logs en `tests/unit/test_logging_redaction.py`: `RedactingFilter` sustituye por `***` estos valores:
  - en `extra` y en `args`, los de las claves `password`, `pass`, `secret`, `token`, `code`, `cookie`, `authorization`, `session`, `csrf`, `email`, `ip`, `client`, `remote_addr` y `db_url`;
  - en el mensaje, los correos, los códigos con formato `XXXX-XXXX-XXXX-XXXX-XXXX`, las direcciones IPv4 e IPv6 completas y la contraseña de una URL de conexión (`mssql+pyodbc://u:secreto@h` → `//u:***@h`).

  Además, el formateador JSON produce una línea por evento, y `AccessLogMiddleware` (sobre una app ASGI mínima) registra método, ruta sin query string, estado, duración e `ip_prefix`, sin la dirección completa ni la query (R14).
- [ ] T012 [P] Test unitario de contraseñas en `tests/unit/test_passwords.py`:
  - **Rechazos**: menos de 12 o más de 128 caracteres tras NFKC; una contraseña de la lista común (con un fichero `.gz` sintético inyectado); una que contenga, sin distinguir mayúsculas, la parte local completa del correo (`anaperez@…` → rechaza `xxANAPEREZxx…`) o una palabra completa de 4 o más caracteres del nombre (`Ana Martínez` → rechaza `…martínez…`); un único carácter repetido.
  - **No rechazos** (FR-016): una parte local de menos de 4 caracteres (`ana@…`) o un fragmento de una palabra del nombre (`mart` de `Martínez`) no provocan rechazo.
  - **Mensajes**: cada rechazo devuelve el mensaje en español de la regla incumplida.
  - **Hash**: el hash y la verificación argon2 funcionan, y `verify_dummy()` existe para igualar los tiempos (R4 y R5).
- [ ] T013 [P] Test unitario de la decisión del límite de intentos en `tests/unit/test_ratelimit_decision.py`, con la función pura `decide(pair_failures, ip_failures, email_failures_1h, settings)` que devuelve un `Decision` con `allow`, `blocked_pair` o `blocked_ip` y un retardo en segundos (no duerme):
  - 5 fallos del par → `blocked_pair`;
  - 20 fallos de la IP → `blocked_ip`;
  - 49 fallos del correo → retardo 0;
  - 50 → 0,5 s;
  - 70 → 10 s (tope);
  - nunca hay bloqueo total por correo;
  - con otros umbrales en `settings` (por ejemplo, 3 fallos del par) la decisión cambia en consecuencia (R10, FR-002, FR-030, FR-030a y FR-031).
- [ ] T014 [P] Test unitario de CSRF en `tests/unit/test_csrf.py`:
  - el token con sesión es `HMAC(k_csrf, session_id)` y la verificación es en tiempo constante;
  - el doble envío anónimo es válido con el par nonce/HMAC correcto e inválido con cualquier alteración;
  - un `Origin` distinto de `GARMIN_HUB_PUBLIC_URL` se rechaza;
  - con una app mínima que aplica `require_csrf` a un router con una ruta `POST` que recibe `Form` (`nombre`), una petición con token válido llega a la ruta **con** el campo `nombre`, y una sin token recibe 403 (R9).
- [ ] T015 [P] Test unitario de cabeceras en `tests/unit/test_security_headers.py`. Usa `TestClient` sobre `/healthz` con una app creada con un engine falso que no se llega a usar. Comprueba que las cabeceras coinciden exactamente con las de research R12:
  - CSP;
  - `X-Content-Type-Options: nosniff`;
  - `Referrer-Policy: same-origin`;
  - `Permissions-Policy`;
  - HSTS solo si `GARMIN_HUB_PUBLIC_URL` es https.
- [ ] T016 [P] Test de integración de la migración en `tests/integration/test_migration_0001.py`, en un schema aleatorio:
  - `upgrade head` crea las 6 tablas de data-model.md con sus índices (`UX_app_user_email`, `UX_invitation_pending_email`, `UX_reset_pending_user`, `IX_invitation_created_at`, `IX_user_session_user`, `IX_user_session_expires`, `IX_login_attempt_email`, `IX_login_attempt_ip`, `IX_audit_event_occurred` e `IX_audit_event_subject`) y el trigger `TR_audit_event_immutable`;
  - `downgrade base` lo elimina todo;
  - un segundo `upgrade head` vuelve a funcionar.
- [ ] T017 [P] Test de integración de auditoría en `tests/integration/test_audit_immutable.py`:
  - `record_event` inserta una fila;
  - un `UPDATE` o `DELETE` sobre `audit_event` falla con el error 51000 `audit_event is insert-only`;
  - `record_event` rechaza claves de `details` fuera de la lista blanca de `contracts/audit-events.md`;
  - la columna se llama `ip_prefix` y `record_event` rechaza un valor que sea una dirección completa en vez de un prefijo.
- [ ] T018 [P] Test unitario de direcciones de red en `tests/unit/test_ip.py` (R11):
  - `ip_prefix("203.0.113.57") == "203.0.113.0/24"` e `ip_prefix("2001:db8:1:2::5") == "2001:db8:1::/48"`;
  - una dirección no válida da `"unknown"`;
  - `ip_hmac(keys, ip)` tiene 32 bytes, es determinista y no contiene la dirección;
  - `client_ip(request)` devuelve `request.client.host`, o `"unknown"` si no hay cliente.

### Implementación fundacional

- [ ] T019 [P] Implementar `utc_now()` en `src/garmin_hub/clock.py`, que devuelve un `datetime` con zona horaria UTC, y el alias de tipo `Clock = Callable[[], datetime]`.
- [ ] T020 [P] Implementar en `src/garmin_hub/secrets.py`:
  - el `Protocol` `SecretProvider` con `get(name: str) -> str | None`;
  - `EnvSecretProvider(fallback: Mapping[str, str] = {})`, que consulta `os.environ` y después `fallback` (el mapa de `load_env_file`);
  - `REQUIRED_SECRETS = ("GARMIN_HUB_DB_URL", "GARMIN_HUB_SESSION_SECRET")`;
  - el dataclass congelado `Secrets`;
  - `load_secrets(provider) -> Secrets`, que valida que el secreto de sesión tenga 32 bytes o más;
  - `MissingSecretsError`, con el mensaje en español "faltan secretos obligatorios: …" (R13 y FR-001).
- [ ] T021 [P] Implementar en `src/garmin_hub/config.py`:
  - `load_env_file(path=Path(".env")) -> Mapping[str, str]` con `dotenv_values`, según R13 (solo si `GARMIN_HUB_ENV=dev` en el entorno real o en el fichero);
  - `Settings` (pydantic-settings, prefijo `GARMIN_HUB_`), que recibe ese mapa como respaldo, con `env`, `public_url` (**obligatoria**, URL http(s)), `db_schema="gh"`, `trusted_proxies="127.0.0.1"`, `log_dir=Path("logs")` y `log_level="INFO"`, y todos los tiempos y límites de FR-002 con los valores por defecto de data-model.md;
  - `load_settings(env_file_values) -> Settings`, que convierte los errores de validación de `public_url` en `MissingConfigError` con el mensaje en español de `contracts/cli.md`;
  - rutas siempre con `pathlib`.

  Debe pasar T009.
- [ ] T022 [P] Implementar `derive_keys(session_secret) -> DerivedKeys` en `src/garmin_hub/keys.py` (HMAC-SHA256 con las etiquetas `session-id`, `csrf`, `code`, `email-rl`, `ip-rl` y `anon-csrf`) y `hmac_digest(key, text) -> bytes` (R7).
- [ ] T023 [P] Implementar en `src/garmin_hub/logging_setup.py`:
  - `JsonFormatter`;
  - `RedactingFilter`;
  - `configure_logging(settings)`, con stderr más `RotatingFileHandler` (10 MB × 5) en `settings.log_dir`, creando el directorio con `pathlib`; el filtro también se aplica al logger `uvicorn.error`;
  - `AccessLogMiddleware` (ASGI puro), que sustituye al log de acceso de uvicorn: método, ruta sin query string, estado, duración e `ip_prefix` (R11 y R14).

  Debe pasar T011.
- [ ] T024 [P] Implementar `client_ip(request)`, `ip_prefix(ip)` e `ip_hmac(keys, ip)` en `src/garmin_hub/security/ip.py` con el módulo `ipaddress` de la librería estándar (R11). Debe pasar T018.
- [ ] T025 Implementar `create_engine_from(secrets, settings)` en `src/garmin_hub/db/engine.py`: `mssql+pyodbc`, `pool_pre_ping=True` y `fast_executemany=True`. También `check_schema_at_head(engine, settings) -> bool`, que compara la revisión de Alembic del schema con `head`.
- [ ] T026 Definir en `src/garmin_hub/db/schema.py` el `MetaData(schema=settings.db_schema)` con las 6 tablas de data-model.md.

  **`app_user`**:
  - `user_id UNIQUEIDENTIFIER PK`
  - `email NVARCHAR(254) NOT NULL UNIQUE (UX_app_user_email)`
  - `display_name NVARCHAR(100) NOT NULL`
  - `password_hash VARCHAR(255) NOT NULL`
  - `role VARCHAR(16) NOT NULL CHECK IN ('user','admin')`
  - `status VARCHAR(20) NOT NULL CHECK IN ('active','deactivated','pending_deletion')`
  - `created_at`, `updated_at` y `password_changed_at`: `DATETIME2(3) NOT NULL`
  - `last_login_at DATETIME2(3) NULL`

  **`invitation`**:
  - `invitation_id UNIQUEIDENTIFIER PK`
  - `code_hash BINARY(32) NOT NULL UNIQUE`
  - `email NVARCHAR(254) NOT NULL`
  - `note NVARCHAR(200) NULL`
  - `status VARCHAR(16) NOT NULL CHECK IN ('pending','used','revoked','expired')`
  - `created_at` y `expires_at`: `NOT NULL`, con `CHECK expires_at > created_at`
  - `created_by_user_id`, `used_by_user_id` y `revoked_by_user_id`: `NULL`, `FK → app_user NO ACTION`
  - `used_at` y `revoked_at`: `NULL`
  - índice único filtrado `UX_invitation_pending_email (email) WHERE status='pending'` e índice `IX_invitation_created_at`

  **`password_reset_code`**:
  - `reset_id UNIQUEIDENTIFIER PK`
  - `user_id NOT NULL FK → app_user NO ACTION`
  - `code_hash BINARY(32) NOT NULL UNIQUE`
  - `status VARCHAR(16) NOT NULL CHECK IN ('pending','used','superseded','expired')`
  - `created_at` y `expires_at`: `NOT NULL`
  - `created_by_user_id NULL`, sin FK
  - `used_at NULL`
  - `UX_reset_pending_user (user_id) WHERE status='pending'`

  **`user_session`**:
  - `session_hash BINARY(32) PK`
  - `user_id NOT NULL FK → app_user NO ACTION`
  - `created_at`, `last_seen_at` y `expires_at`: `NOT NULL`
  - `IX_user_session_user` e `IX_user_session_expires`

  **`login_attempt`**:
  - `attempt_id BIGINT IDENTITY PK`
  - `attempted_at NOT NULL`
  - `email_hmac BINARY(32) NULL`
  - `ip_hmac BINARY(32) NOT NULL`
  - `kind VARCHAR(20) NOT NULL CHECK IN ('login','code_redeem','current_password')`
  - `succeeded BIT NOT NULL`
  - `IX_login_attempt_email (email_hmac, attempted_at)` e `IX_login_attempt_ip (ip_hmac, attempted_at)`

  **`audit_event`**:
  - `audit_id BIGINT IDENTITY PK`
  - `occurred_at NOT NULL`
  - `event_type VARCHAR(64) NOT NULL`
  - `actor_user_id` y `subject_user_id`: `UNIQUEIDENTIFIER NULL`, **sin FK**
  - `ip_prefix VARCHAR(50) NULL` (red reducida, nunca la dirección completa)
  - `details NVARCHAR(1000) NULL`
  - `IX_audit_event_occurred` e `IX_audit_event_subject`
- [ ] T027 Implementar el entorno de Alembic en `src/garmin_hub/db/migrations/env.py` y `src/garmin_hub/db/migrations/script.py.mako`:
  - la configuración es programática, sin `alembic.ini`;
  - `version_table_schema=settings.db_schema`;
  - crea el schema si no existe;
  - expone `run_upgrade(engine, settings, revision="head")` y `run_downgrade(...)` en `src/garmin_hub/db/migrate.py`.
- [ ] T028 Escribir la migración `src/garmin_hub/db/migrations/versions/0001_user_access.py`:
  - **`upgrade`** crea:
    - las 6 tablas, índices y CHECK de T026;
    - el trigger `TR_audit_event_immutable INSTEAD OF UPDATE, DELETE` con `THROW 51000, 'audit_event is insert-only', 1`;
    - el `DENY UPDATE, DELETE ON audit_event TO gh_app`, solo si existe el rol `gh_app`.
  - **`downgrade`** lo elimina todo en orden inverso. Debe pasar T016.
- [ ] T029 Implementar `record_event(conn, event_type, *, actor_user_id, subject_user_id, ip_prefix, details, now)` en `src/garmin_hub/accounts/audit.py`:
  - la lista blanca `ALLOWED_DETAILS: dict[str, frozenset[str]]` copiada de `contracts/audit-events.md`;
  - rechaza tipos de evento o claves no listados con `ValueError`, y también un `ip_prefix` que no tenga la forma `red/longitud`;
  - serializa `details` a JSON.

  Debe pasar T017.
- [ ] T030 [P] Implementar en `src/garmin_hub/security/passwords.py`:
  - `hash_password`, `verify_password` (con `check_needs_rehash`) y `verify_dummy()` (hash señuelo precalculado);
  - `validate_password(password, *, email, display_name) -> str | None`, que devuelve el mensaje de error en español o `None` según las reglas de R5;
  - la carga perezosa de `common_passwords.txt.gz` con `importlib.resources`.

  Debe pasar T012.
- [ ] T031 [P] Implementar en `src/garmin_hub/security/ratelimit.py`:
  - la función pura `decide(...)`;
  - `check_attempts(conn, *, email, ip, kind, keys, settings, now) -> Decision`, que cuenta en `login_attempt` según R10 (fallos `login` y `current_password` del par posteriores al último acierto del par; fallos `login` y `code_redeem` de la IP; fallos `login` del correo en 60 min) y **devuelve** la decisión con el retardo, sin dormir;
  - `record_attempt(conn, *, email, ip, kind, succeeded, keys, now)`, que guarda `email_hmac` e `ip_hmac`, nunca el correo ni la dirección;
  - `purge_old_attempts(conn, now)` para las filas de más de 24 h.

  Debe pasar T013.
- [ ] T032 [P] Implementar en `src/garmin_hub/security/sessions.py`:
  - `create_session(conn, user_id, keys, settings, now) -> str`, que devuelve el id en claro y guarda solo el HMAC;
  - `resolve_session(conn, raw_id, keys, settings, now) -> SessionUser | None`, que hace JOIN con `app_user.status='active'`, comprueba inactividad y caducidad absoluta, borra la sesión si no es válida y actualiza `last_seen_at` como mucho cada 60 s;
  - `delete_session`, `delete_user_sessions(conn, user_id, except_hash=None) -> int` y `purge_expired_sessions(conn, now)` (`TOP 500`);
  - las constantes de la cookie: siempre `__Host-gh_session` con `HttpOnly`, `Secure`, `SameSite=Lax` y `Path=/`, en todos los entornos (R8).
- [ ] T033 [P] Implementar en `src/garmin_hub/security/csrf.py`:
  - `session_token(keys, session_id)`, `new_anon_pair(keys)` y `verify(...)`;
  - la dependencia de FastAPI `require_csrf(request)` (`async`), que en POST, PUT, PATCH y DELETE lee `X-CSRF-Token` o el campo `csrf_token` con `await request.form()` (queda en caché para la ruta), comprueba `Origin` y lanza `CsrfError`, que un manejador convierte en 403 con la plantilla `errors/csrf.html`. La cookie anónima es siempre `__Host-gh_csrf` (R9).

  Debe pasar T014.
- [ ] T034 [P] Implementar `SecurityHeadersMiddleware` en `src/garmin_hub/security/headers.py`, con las cabeceras de R12 y `Cache-Control: no-store` cuando hay usuario autenticado. Debe pasar T015.
- [ ] T035 Implementar `create_app(settings, secrets, *, engine=None, clock=utc_now, sleep=anyio.sleep)` en `src/garmin_hub/web/app.py`:
  - monta `static/`, Jinja2 con autoescape, `AccessLogMiddleware` y el middleware de cabeceras;
  - define el manejador de `CsrfError` (403) e incluye cada router con `dependencies=[Depends(require_csrf)]`;
  - define el manejador de 404 y 500 con plantillas en español;
  - define `GET /healthz → "ok"`;
  - guarda `engine`, `keys`, `clock` y `sleep` en `app.state`.
- [ ] T036 Implementar en `src/garmin_hub/web/deps.py`:
  - `get_conn` (una transacción por petición);
  - `current_user` (lee la cookie y llama a `resolve_session`);
  - `require_user`, que redirige con 303 a `/login`, o devuelve `HX-Redirect` si la petición es HTMX;
  - `require_admin`, que lanza 404 si el usuario no es administrador;
  - reexporta `require_csrf` (T033) y `client_ip` (`security/ip.py`) para las rutas.
- [ ] T037 [P] Crear las plantillas base en español:
  - `src/garmin_hub/web/templates/base.html`, con `<meta name="htmx-config" content='{"includeIndicatorStyles":false}'>`, `hx-headers` con el token CSRF en `<body>`, la navegación (con el enlace de administración solo para administradores), un bloque de mensajes y sin scripts ni estilos inline;
  - `src/garmin_hub/web/templates/errors/404.html`, `errors/500.html` y `errors/csrf.html`;
  - `src/garmin_hub/web/static/css/app.css`, con estilos mínimos.
- [ ] T038 Implementar el CLI base en `src/garmin_hub/cli/main.py`:
  - la `app` de Typer con los grupos `db`, `admin` y `web`;
  - un callback común que llama a `load_env_file()`, carga `load_settings(...)` y `load_secrets(EnvSecretProvider(fallback=...))`, configura el logging y convierte `MissingSecretsError` y `MissingConfigError` en los mensajes de `contracts/cli.md` y la salida 2;
  - el comando `web serve [--host 127.0.0.1] [--port 8000] [--reload]`, que comprueba la conexión y `check_schema_at_head` (salida 3 si falla) y lanza uvicorn con `proxy_headers=True`, `forwarded_allow_ips=settings.trusted_proxies` y `access_log=False`. `--reload` solo se permite con `env=dev`.
- [ ] T039 Crear las fixtures compartidas en `tests/conftest.py`:
  - `settings` con valores de test (`public_url="https://testserver"`);
  - `secrets` sintéticos;
  - `FakeClock` avanzable;
  - `fake_sleep`, una función `async` que registra los retardos sin dormir;
  - `common_passwords` sintético.
- [ ] T040 Crear las fixtures de integración en `tests/integration/conftest.py`:
  - si falta `GARMIN_HUB_TEST_DB_URL`, se omiten los tests marcados `integration`;
  - schema aleatorio `gh_t_<hex>` con `run_upgrade` al empezar y `run_downgrade` más `DROP SCHEMA` al terminar;
  - `engine`;
  - `client`, un `TestClient(app, base_url="https://testserver")` con `create_app` que usa `FakeClock` y `fake_sleep` (https para que `httpx` envíe las cookies `Secure`, R8);
  - `make_user(role="user", status="active", password=...)`, que inserta directamente en `app_user`;
  - `login_as(client, user)`, que crea la sesión con `create_session` y pone la cookie `__Host-gh_session`;
  - `csrf_for(client)`, que devuelve el token CSRF de la sesión o del formulario anónimo;
  - `captured_logs`, con un handler en memoria detrás de `RedactingFilter`;
  - `audit_rows(event_type=None)`.

**Checkpoint**: `uv run ruff check`, `uv run pytest` (T009–T015 y T018 en verde) y `uv run pytest -m integration` (T016 y T017 en verde). La base está lista.

---

## Phase 3: User Story 1 - Crear el primer administrador desde la línea de comandos (Priority: P1) 🎯 MVP

**Goal**: un operador crea un administrador con `garmin-hub admin create` en una base recién migrada con `garmin-hub db upgrade`.

**Independent Test**: ejecutar `db upgrade` dos veces y `admin create` en un schema vacío; existe un `app_user` con `role='admin'`, la contraseña no aparece en la salida y queda el evento `admin.created`.

### Tests for User Story 1 ⚠️

- [ ] T041 [P] [US1] Test del contrato CLI para `db upgrade` en `tests/integration/test_cli_db.py` (marca `integration`), con `CliRunner`: dos ejecuciones seguidas devuelven 0 con el mensaje `Base de datos actualizada a la revisión <rev>.`, y el schema queda en `head`.
- [ ] T042 [P] [US1] Test del contrato CLI para `admin create` en `tests/integration/test_cli_admin_create.py`:
  - si todo va bien, sale con 0 y `Administrador creado: <uuid>`, la salida no contiene ni el correo ni la contraseña, la fila tiene `role='admin'` y `status='active'`, y queda `admin.created` con `{"via":"cli"}`;
  - un correo duplicado sale con 1 y no crea nada;
  - un correo con una invitación pendiente (insertada directamente) sale con 1 y no crea nada;
  - una contraseña que incumple la política sale con 1 y muestra el mensaje en español de la regla;
  - si las dos contraseñas introducidas no coinciden, falla;
  - no existe la opción `--password`;
  - si el schema no está en `head`, sale con 3.
- [ ] T043 [P] [US1] Test unitario del CLI sin secretos en `tests/unit/test_cli_missing_secrets.py`, ejecutado en un `tmp_path` sin `.env`: con `GARMIN_HUB_SESSION_SECRET` sin definir, `admin create`, `db upgrade` y `web serve` salen con 2 y muestran el mensaje exacto de `contracts/cli.md`, sin ningún valor (FR-001); sin `GARMIN_HUB_PUBLIC_URL`, salen con 2 y el mensaje de configuración obligatoria.

### Implementation for User Story 1

- [ ] T044 [US1] Implementar en `src/garmin_hub/accounts/users.py`:
  - `normalize_email(email) -> str` (`strip().lower()`) y `validate_email(email) -> str | None`, con un formato básico y un mensaje en español;
  - `validate_display_name(name) -> str | None` (de 1 a 100 caracteres sin espacios alrededor);
  - `create_admin(conn, *, email, display_name, password, now) -> UUID`, que valida la contraseña con `validate_password`, comprueba que el correo sea único y que no tenga una invitación `pending` no caducada, inserta `role='admin'` y `status='active'`, y registra `admin.created` con `actor_user_id=None` e `ip_prefix=None`.
- [ ] T045 [US1] Añadir los comandos `db upgrade [--revision head]` (con `run_upgrade`) y `admin create --email --name` en `src/garmin_hub/cli/main.py`. `admin create` pide la contraseña con `typer.prompt(hide_input=True, confirmation_prompt=True)` y usa los códigos de salida 0, 1 y 3 y los mensajes en español de `contracts/cli.md`.

**Checkpoint**: T041–T043 en verde. Se puede crear un administrador desde una instalación vacía (pasos 0–2 de quickstart).

---

## Phase 4: User Story 2 - Generar una invitación (Priority: P1)

**Goal**: el administrador genera desde la web invitaciones de un solo uso ligadas a un correo, con caducidad y nota, y ve el listado.

**Independent Test**: con `login_as(admin)`, `POST /admin/invitaciones` con un correo muestra un código una sola vez, y `GET /admin/invitaciones` lo lista como "Pendiente" sin el código.

### Tests for User Story 2 ⚠️

- [ ] T046 [P] [US2] Test unitario de códigos en `tests/unit/test_codes.py`:
  - `generate_code()` produce 20 caracteres en base32 de Crockford con el formato `XXXX-XXXX-XXXX-XXXX-XXXX`;
  - `normalize_code` pasa a mayúsculas, quita guiones y espacios y convierte O→0 e I/L→1;
  - `code_hash(keys, code)` es igual para variantes equivalentes y tiene 32 bytes (R6).
- [ ] T047 [P] [US2] Test de integración del servicio de invitaciones en `tests/integration/test_invitations_create.py`:
  - **TTL**: sin indicarlo, `expires_at = created_at + 7 días`; con `settings.invite_ttl_days=3`, el valor por defecto pasa a 3 días (FR-002); con `ttl_days=2`, son 2 días; fuera del rango 1–30 se rechaza.
  - **Almacenamiento**: solo se guarda `code_hash`; el código en claro no está en ninguna columna.
  - **Rechazos de correo**: un correo con formato no válido; un correo ya registrado en `app_user`; un correo que ya tiene una invitación pendiente.
  - **Caducadas**: una pendiente caducada del mismo correo pasa a `expired` y se permite crear otra.
  - **Auditoría**: queda `invitation.created` con `{"invitation_id","ttl_days"}`.
- [ ] T048 [P] [US2] Test HTTP y de autorización en `tests/integration/test_admin_invitations_http.py`:
  - como administrador, `POST /admin/invitaciones` devuelve 200 con un fragmento que contiene el código;
  - `GET /admin/invitaciones` muestra el correo, "Pendiente", la nota y las fechas, pero no el código;
  - un usuario normal recibe 404 en `GET` y `POST /admin/invitaciones`;
  - un usuario sin sesión recibe 303 a `/login`;
  - un POST sin CSRF recibe 403;
  - los errores 422 muestran los mensajes en español.

### Implementation for User Story 2

- [ ] T049 [P] [US2] Implementar `generate_code`, `format_code`, `normalize_code` y `code_hash` en `src/garmin_hub/security/codes.py` con `secrets` (R6). Debe pasar T046.
- [ ] T050 [US2] Implementar en `src/garmin_hub/accounts/invitations.py`:
  - `create_invitation(conn, *, admin_id, email, note, ttl_days, keys, settings, now) -> tuple[UUID, str]`:
    - normaliza el correo;
    - rechaza si el correo existe en `app_user`;
    - materializa como `expired` las pendientes caducadas de ese correo;
    - inserta, apoyándose en `UX_invitation_pending_email` para detectar duplicados y traducir el error a un mensaje en español;
    - registra `invitation.created`;
  - `list_invitations(conn, now)`, con el estado efectivo "Pendiente", "Usada", "Caducada" o "Revocada".

  Debe pasar T047.
- [ ] T051 [US2] Implementar `GET /admin/invitaciones` y `POST /admin/invitaciones` (`email`, `note?` y `ttl_days?`) en `src/garmin_hub/web/routes/admin.py` con `require_admin`, y registrar el router en `src/garmin_hub/web/app.py`.
- [ ] T052 [P] [US2] Crear las plantillas en español:
  - `src/garmin_hub/web/templates/admin/invitations.html`, con el formulario y la tabla;
  - `src/garmin_hub/web/templates/admin/_invitation_created.html`, con el código visible una sola vez y el aviso "Copia este código ahora; no se volverá a mostrar".

**Checkpoint**: T046–T048 en verde. US2 funciona de forma independiente.

---

## Phase 5: User Story 3 - Completar el alta con un código (Priority: P1)

**Goal**: la persona invitada canjea el código, ve su correo fijo, pone su nombre y contraseña y entra con la sesión iniciada.

**Independent Test**: con una invitación creada por el servicio, recorrer `/alta` → `/alta/codigo` → `POST /alta` crea el usuario e inicia sesión; repetir el canje da el mensaje genérico.

### Tests for User Story 3 ⚠️

- [ ] T053 [P] [US3] Test de integración del alta en `tests/integration/test_signup_http.py`:
  - **Alta correcta**: con un código válido, `POST /alta/codigo` devuelve 200 con el correo de la invitación en solo lectura, y `POST /alta` devuelve 303 a `/` con la cookie de sesión. El usuario queda con `role='user'`, la invitación pasa a `used` con `used_by_user_id` y queda `user.signed_up`.
  - **Códigos no válidos**: uno usado, caducado (`FakeClock` adelantado), revocado (con `status` puesto directamente) o inexistente da 422 con exactamente "El código no es válido o ha caducado." y `auth.code_redeem_failed`.
  - **Correo manipulado**: un campo `email` distinto del de la invitación da el mensaje genérico, sin consumir el código.
  - **Contraseña**: una trivial o de 11 caracteres da 422 con el mensaje de la regla, sin consumir el código.
  - **Formulario**: si `password_confirm` no coincide, da 422.
  - **Correo ya registrado por otra vía**: si tras crear la invitación se inserta directamente un `app_user` con ese correo, `POST /alta` da 422 con el mensaje genérico de código y la invitación sigue `pending`.
- [ ] T054 [P] [US3] Test de concurrencia en `tests/integration/test_signup_concurrency.py`: dos hilos con conexiones distintas canjean el mismo código a la vez y se crea exactamente un `app_user` (FR-009 y SC-002).
- [ ] T055 [P] [US3] Test del límite de canje por origen en `tests/integration/test_signup_ratelimit.py`: 20 canjes fallidos desde la misma IP en 15 min bloquean el siguiente, aunque el código sea válido, con el mismo mensaje genérico; desde otra IP el canje funciona (FR-031).

### Implementation for User Story 3

- [ ] T056 [US3] Implementar en `src/garmin_hub/accounts/invitations.py`:
  - `peek_invitation(conn, code, keys, now) -> Invitation | None`, que devuelve la invitación pendiente y no caducada;
  - `redeem_invitation(conn, *, code, display_name, password, keys, now) -> UUID`, en una sola transacción:
    - valida el nombre y la contraseña con `validate_password` usando el correo de la invitación;
    - ejecuta `UPDATE invitation SET status='used', used_at=?, used_by_user_id=? WHERE code_hash=? AND status='pending' AND expires_at>?`;
    - si `rowcount != 1`, lanza `InvalidCode`;
    - inserta `app_user` con `role='user'` y `status='active'`; si viola `UX_app_user_email`, revierte la transacción y lanza `InvalidCode` (R17);
    - registra `user.signed_up`.

    Si la validación falla, no consume el código.
- [ ] T057 [US3] Implementar `GET /alta`, `POST /alta/codigo` y `POST /alta` en `src/garmin_hub/web/routes/signup.py`:
  - CSRF anónimo de doble envío;
  - las rutas POST son `async def`: `check_attempts`, el canje y `record_attempt` (`kind='code_redeem'`) van con `run_in_threadpool`, y el retardo, si lo hay, con `await app.state.sleep(delay)` fuera de la transacción (R10);
  - `auth.code_redeem_failed` con `{"kind":"invitation","reason":...}`;
  - si el alta va bien, `create_session`, cookie y 303 a `/`;
  - registrar el router en `src/garmin_hub/web/app.py`.
- [ ] T058 [P] [US3] Crear las plantillas en español `src/garmin_hub/web/templates/signup_code.html` (paso 1) y `src/garmin_hub/web/templates/signup_details.html` (paso 2: correo en solo lectura, código oculto, nombre, contraseña y confirmación, y ayuda sobre la política de contraseñas).
- [ ] T059 [P] [US3] Crear `src/garmin_hub/web/templates/home.html` y `GET /` en `src/garmin_hub/web/routes/account.py` con `require_user`: una página de inicio con el nombre del usuario, que servirá de marcador para las features posteriores.

**Checkpoint**: T053–T055 en verde. Una persona invitada completa su alta (paso 5 de quickstart, en menos de 2 min).

---

## Phase 6: User Story 4 - Iniciar y cerrar sesión (Priority: P1)

**Goal**: inicio de sesión con mensajes genéricos, límites de intentos, cierre de sesión y caducidad por inactividad y por duración máxima.

**Independent Test**: con `make_user`, `POST /login` entra; `POST /logout` invalida la sesión; con `FakeClock` adelantado 31 min, la siguiente petición redirige a `/login`.

### Tests for User Story 4 ⚠️

- [ ] T060 [P] [US4] Test de integración del inicio de sesión en `tests/integration/test_login_http.py`:
  - **Inicio correcto**: 303 a `/`, cookie `__Host-gh_session` con `HttpOnly`, `Secure`, `SameSite=Lax` y `Path=/`, `last_login_at` actualizado y `auth.login_succeeded` con `ip_prefix` y no la dirección completa.
  - **Fallos**: una contraseña errónea, un correo inexistente, un usuario `deactivated` y uno `pending_deletion` dan el mismo 422 con exactamente "Correo o contraseña incorrectos.", y `auth.login_failed` con el `reason` correspondiente.
  - **Tiempos**: con un correo inexistente se llama a `verify_dummy()` (comprobado con monkeypatch).
  - **Correo**: se normaliza al iniciar sesión (`" Ana@Club.TEST "`).
  - **Sesión nueva**: cada inicio de sesión crea una sesión con otro id.
- [ ] T061 [P] [US4] Test de integración de la sesión en `tests/integration/test_session_lifecycle.py`:
  - `POST /logout` borra la fila de `user_session`, y reutilizar la cookie redirige a `/login`;
  - con 31 min de inactividad, la petición redirige a `/login`; con `settings.session_idle_minutes=10`, ya redirige a los 11 min (FR-002);
  - con actividad continua, tras 12 h redirige;
  - una petición HTMX sin sesión recibe `HX-Redirect: /login`;
  - una sesión de un usuario que pasa a `deactivated` deja de valer en la siguiente petición;
  - las respuestas autenticadas llevan `Cache-Control: no-store`;
  - queda `auth.logout`.
- [ ] T062 [P] [US4] Test de integración de los límites de intentos en `tests/integration/test_login_ratelimit.py`:
  - **Por par**: 5 fallos del par correo + IP-A en 15 min bloquean el sexto intento aunque la contraseña sea correcta, con el mensaje genérico y `auth.login_failed{reason:"blocked_pair"}`; desde la IP-B se entra.
  - **Por IP**: 20 fallos desde la IP-A (con correos distintos) bloquean la IP.
  - **Global por correo**: con 50 fallos repartidos en varias IP en 1 h, el siguiente intento registra en `fake_sleep` 0,5 s; con 70, 10 s. Se entra igualmente con la contraseña correcta, y se registra `auth.email_soft_limit` una vez al cruzar el umbral.
  - **Reinicio**: tras 4 fallos del par y un acierto, otros 4 fallos no bloquean.
  - **Sin bloqueo de hilos**: `POST /login` es una corrutina (`inspect.iscoroutinefunction`) y el retardo se pide a `app.state.sleep`, no a `time.sleep`.
  - **Seudonimización**: `login_attempt.email_hmac` nunca coincide con el correo en claro y `login_attempt` no tiene ninguna columna con la dirección de red en claro.

### Implementation for User Story 4

- [ ] T063 [US4] Implementar `authenticate(conn, *, email, password, ip, decision, keys, settings, now) -> UUID | AuthFailure` en `src/garmin_hub/accounts/users.py`, que recibe la `Decision` ya calculada por `check_attempts` (el retardo lo espera la ruta):
  - normaliza el correo;
  - verifica siempre una contraseña: la real o `verify_dummy()` si el usuario no existe, no está `active` o está bloqueado;
  - llama a `record_attempt`;
  - actualiza `last_login_at` y vuelve a calcular el hash si `check_needs_rehash` lo pide;
  - registra `auth.login_succeeded`, `auth.login_failed` o `auth.email_soft_limit`.
- [ ] T064 [US4] Implementar `GET /login`, `POST /login` y `POST /logout` en `src/garmin_hub/web/routes/auth.py`:
  - CSRF anónimo en el inicio de sesión y CSRF de sesión en el cierre;
  - `POST /login` es `async def`: `check_attempts` con `run_in_threadpool`, `await app.state.sleep(decision.delay)` fuera de la transacción y después `authenticate` con `run_in_threadpool` (R10);
  - tras un inicio correcto, `purge_expired_sessions`, `purge_old_attempts` y `create_session`;
  - en el cierre, `delete_session`, borrado de la cookie y `auth.logout`;
  - los avisos `?restablecida=1` y `?eliminada=1` se muestran en la página de inicio de sesión;
  - registrar el router en `src/garmin_hub/web/app.py`.
- [ ] T065 [P] [US4] Crear la plantilla `src/garmin_hub/web/templates/login.html` en español y añadir a `base.html` el botón "Cerrar sesión" como formulario POST con CSRF.

**Checkpoint**: T060–T062 en verde. Las cuatro historias P1 funcionan juntas (pasos 3–7 de quickstart). **MVP completo.**

---

## Phase 7: User Story 5 - Cambiar la contraseña, editar el nombre y exportar mis datos (Priority: P2)

**Goal**: el usuario edita su nombre, cambia su contraseña indicando la actual (sus demás sesiones se cierran) y descarga una exportación de sus datos.

**Independent Test**: con `login_as(user)` en dos clientes, cambiar la contraseña desde uno deja el otro redirigido a `/login`; `GET /cuenta/exportar` descarga su perfil.

### Tests for User Story 5 ⚠️

- [ ] T066 [P] [US5] Test de integración del perfil en `tests/integration/test_account_profile_http.py`:
  - **Nombre**: `POST /cuenta/nombre` actualiza `display_name` y queda `user.name_changed`; un nombre vacío o de 101 caracteres da 422 en español.
  - **Contraseña correcta**: con la actual correcta y una nueva válida, `POST /cuenta/contrasena` cambia la contraseña, la sesión del otro cliente queda invalidada y la actual sigue abierta. Queda `user.password_changed{sessions_closed:1}`.
  - **Contraseña actual errónea**: da 422, se registra un `login_attempt` con `kind='current_password'` y queda `user.password_change_failed`. Cinco fallos bloquean el par (correo + IP), también para `POST /login` desde esa IP; esos fallos no cuentan para el límite por IP (FR-030 y FR-031).
  - **Contraseña nueva no válida**: da 422 con la regla incumplida.
- [ ] T067 [P] [US5] Test de autorización en `tests/integration/test_account_authz.py`:
  - un usuario A no puede modificar a un usuario B, porque las rutas `/cuenta/*` solo actúan sobre el usuario de la sesión: un campo `user_id` inyectado en el formulario se ignora y B no cambia;
  - sin sesión, `/cuenta*` (incluida `/cuenta/exportar`) redirige a `/login`;
  - la exportación de A no contiene el correo, el nombre ni los eventos de B.
- [ ] T068 [P] [US5] Test de integración de la exportación en `tests/integration/test_account_export_http.py` (FR-023a):
  - `GET /cuenta/exportar` devuelve 200, `application/json` y `Content-Disposition: attachment; filename="garmin-hub-export.json"`;
  - el JSON tiene `format_version: 1`, `exported_at`, `profile` (nombre, correo, rol, estado, `created_at`, `last_login_at`) y `audit_events` con los eventos cuyo sujeto es el usuario;
  - no contiene `password_hash` ni ningún hash, código o identificador de sesión;
  - una sección registrada con `register_export_section` en el test aparece en el JSON;
  - queda `user.data_exported{sections}`.

### Implementation for User Story 5

- [ ] T069 [US5] Implementar en `src/garmin_hub/accounts/users.py`:
  - `change_display_name(conn, user_id, name, now)`;
  - `change_password(conn, *, user_id, current_password, new_password, current_session_hash, ip, keys, settings, now)`, que comprueba el bloqueo del par con `check_attempts(kind='current_password')` (sin retardo: el límite global por correo solo cuenta `login`), registra el intento, actualiza `password_changed_at`, llama a `delete_user_sessions(except_hash=current)` y registra la auditoría.
- [ ] T070 [US5] Implementar `GET /cuenta`, `POST /cuenta/nombre` y `POST /cuenta/contrasena` en `src/garmin_hub/web/routes/account.py` con `require_user`.
- [ ] T071 [US5] Implementar en `src/garmin_hub/accounts/export.py` el registro `register_export_section(name, fn)` (rechaza nombres duplicados), las secciones propias de 001 (`profile` y `audit_events`) y `build_export(conn, user_id, now) -> dict`, que registra `user.data_exported`; y la ruta `GET /cuenta/exportar` en `src/garmin_hub/web/routes/account.py` con `require_user`, que devuelve el JSON como descarga (FR-023a, `contracts/http.md`). Debe pasar T068.
- [ ] T072 [P] [US5] Crear la plantilla `src/garmin_hub/web/templates/account.html` en español: el correo en solo lectura, el formulario del nombre, el formulario de la contraseña, el enlace "Exportar mis datos" y el enlace "Eliminar mi cuenta".

**Checkpoint**: T066, T067 y T068 en verde (paso 8 de quickstart).

---

## Phase 8: User Story 6 - Administrar usuarios e invitaciones (Priority: P2)

**Goal**: el administrador lista usuarios, los desactiva y reactiva, y revoca invitaciones pendientes, con las protecciones del último administrador.

**Independent Test**: desactivar a un usuario con sesión abierta hace que su siguiente petición vaya a `/login`; al reactivarlo, vuelve a entrar.

### Tests for User Story 6 ⚠️

- [ ] T073 [P] [US6] Test de integración de la administración de usuarios en `tests/integration/test_admin_users_http.py`:
  - **Listado**: `GET /admin/usuarios` muestra nombre, correo, rol, estado ("Activo", "Desactivado" o "Borrado pendiente"), alta y último acceso, y ninguna otra columna de datos.
  - **Desactivar**: devuelve 200 con el fragmento, borra las sesiones del usuario (su cliente es redirigido), impide su inicio de sesión, pasa sus códigos de restablecimiento `pending` a `expired` y deja `user.deactivated{sessions_closed,resets_expired}`.
  - **Reactivar**: permite volver a entrar con la misma contraseña y deja `user.reactivated`.
  - **Rechazos (409)**: reactivar a un usuario activo; que el administrador se desactive a sí mismo; desactivar al último administrador activo.
- [ ] T074 [P] [US6] Test de concurrencia en `tests/integration/test_last_admin_race.py`: dos administradores se desactivan mutuamente en hilos simultáneos y al final queda al menos un administrador activo (R18).
- [ ] T075 [P] [US6] Test de revocación en `tests/integration/test_admin_invitations_revoke.py`:
  - revocar una invitación pendiente la deja en `revoked` y su código da el mensaje genérico en `/alta/codigo`;
  - revocar una ya usada da 409;
  - queda `invitation.revoked`;
  - el listado muestra el estado efectivo "Caducada" con `FakeClock` adelantado y el usuario que usó una invitación.
- [ ] T076 [P] [US6] Test de autorización de las rutas de administración en `tests/integration/test_admin_authz.py`: un usuario normal recibe 404 en **todas** las rutas `/admin/**` de `contracts/http.md`, tanto GET como POST con CSRF válido, y un usuario sin sesión recibe 303 a `/login`. Un `{user_id}` o `{invitation_id}` inexistente devuelve 404 al administrador.

### Implementation for User Story 6

- [ ] T077 [US6] Implementar en `src/garmin_hub/accounts/users.py`:
  - `list_users(conn)`;
  - `deactivate_user(conn, *, admin_id, user_id, ip, now)`, que rechaza al propio administrador, cuenta los administradores activos con `WITH (UPDLOCK, HOLDLOCK)`, pone `status='deactivated'`, llama a `delete_user_sessions`, pasa los códigos de restablecimiento `pending` del usuario a `expired` (FR-029) y registra la auditoría;
  - `reactivate_user(...)`.
- [ ] T078 [US6] Implementar `revoke_invitation(conn, *, admin_id, invitation_id, now)` en `src/garmin_hub/accounts/invitations.py`, que solo admite invitaciones `pending` (si no, `Conflict`) y registra `invitation.revoked`.
- [ ] T079 [US6] Implementar `GET /admin/usuarios`, `POST /admin/usuarios/{user_id}/desactivar`, `POST /admin/usuarios/{user_id}/reactivar` y `POST /admin/invitaciones/{invitation_id}/revocar` en `src/garmin_hub/web/routes/admin.py`, devolviendo fragmentos HTMX y los códigos 409 y 404 de `contracts/http.md`.
- [ ] T080 [P] [US6] Crear las plantillas `src/garmin_hub/web/templates/admin/users.html` y `src/garmin_hub/web/templates/admin/_user_row.html` (fila con acciones `hx-post`), y añadir el botón "Revocar" en `admin/invitations.html`. Todos los textos de estado y error, en español.

**Checkpoint**: T073–T076 en verde (pasos 9 y 12 de quickstart).

---

## Phase 9: User Story 7 - Eliminar mi usuario (Priority: P2)

**Goal**: el usuario se elimina con contraseña y la palabra `ELIMINAR`; el administrador puede borrar a usuarios normales desactivados (FR-028a, escenarios 7–8 de US6). El borrado es reanudable y ampliable mediante pasos registrados.

**Independent Test**: un usuario con sesiones, códigos de restablecimiento e invitaciones a su nombre se elimina; solo quedan filas de `audit_event` con su UUID y sin correo ni nombre.

### Tests for User Story 7 ⚠️

- [ ] T081 [P] [US7] Test unitario del registro de pasos en `tests/unit/test_deletion_registry.py`: `register_deletion_step(name, order, fn)` ordena los pasos por `order` y rechaza nombres duplicados; `run_steps` los ejecuta en orden e informa del primero que falla.
- [ ] T082 [P] [US7] Test de integración del borrado propio en `tests/integration/test_account_delete_http.py`:
  - **Rechazos sin borrado**: una contraseña errónea o una confirmación distinta de `ELIMINAR` dan 422; el último administrador activo recibe 409.
  - **Borrado correcto**: 303 a `/login?eliminada=1`. No queda ninguna fila en `app_user`, `user_session` ni `password_reset_code` del usuario, y las referencias `*_by_user_id` de `invitation` quedan a NULL.
  - **Auditoría**: quedan `user.deletion_requested{by:"self"}` y `user.deleted{by:"self",steps}`.
  - **Después del borrado**: iniciar sesión con su correo da la misma respuesta que con un correo inexistente.
- [ ] T083 [P] [US7] Test de reanudación en `tests/integration/test_deletion_resume.py`:
  - con un paso registrado que falla, el usuario queda en `pending_deletion`, no puede entrar y queda `user.deletion_step_failed{step}`;
  - tras arreglar el paso, `POST /admin/usuarios/{id}/reintentar-borrado` completa el borrado;
  - reintentar sobre un usuario que no está en `pending_deletion` da 409.
- [ ] T084 [P] [US7] Test del borrado por el administrador en `tests/integration/test_admin_delete_user_http.py`:
  - un usuario normal desactivado se borra confirmando con su correo, y queda `user.deleted{by:"admin"}` con el administrador como actor;
  - un correo de confirmación distinto da 422;
  - un usuario activo o un administrador dan 409 (FR-028a).

### Implementation for User Story 7

- [ ] T085 [US7] Implementar en `src/garmin_hub/accounts/deletion.py`:
  - `DeletionContext`, con `engine` y `now`, preparado para añadir `RawStore` en features posteriores;
  - `register_deletion_step` y `run_steps`;
  - los pasos propios de 001, `delete_reset_codes` y `null_invitation_refs`;
  - `request_self_deletion(...)`, que verifica la contraseña y `confirmation == "ELIMINAR"` y comprueba el último administrador;
  - `request_admin_deletion(...)`, solo para `role='user'` con `status='deactivated'` y `confirmation_email` igual al correo del usuario;
  - `execute_deletion(ctx, user_id, by)`, que hace las tres fases de R16 (en la primera, además, pasa los códigos de restablecimiento `pending` a `expired`);
  - `retry_deletion(...)`.
- [ ] T086 [US7] Implementar `GET /cuenta/eliminar` y `POST /cuenta/eliminar` en `src/garmin_hub/web/routes/account.py`; al terminar, borra la cookie y redirige a `/login?eliminada=1`.
- [ ] T087 [US7] Implementar `GET /admin/usuarios/{user_id}/eliminar`, `POST /admin/usuarios/{user_id}/eliminar` y `POST /admin/usuarios/{user_id}/reintentar-borrado` en `src/garmin_hub/web/routes/admin.py`.
- [ ] T088 [P] [US7] Crear las plantillas en español:
  - `src/garmin_hub/web/templates/account_delete.html`, que lista qué se borra: usuario, cuentas Garmin vinculadas, datos descargados, ficheros crudos, consentimientos y membresías;
  - `src/garmin_hub/web/templates/admin/user_delete.html`, que pide escribir el correo del usuario;
  - en `admin/_user_row.html`, las acciones "Eliminar" (solo para usuarios desactivados) y "Reintentar borrado".

**Checkpoint**: T081–T084 en verde (paso 11 de quickstart).

---

## Phase 10: User Story 8 - Restablecer la contraseña con un código del administrador (Priority: P3)

**Goal**: el administrador genera un código de restablecimiento de un solo uso para un usuario activo, y el usuario lo canjea en `/restablecer`.

**Independent Test**: generar un código para un usuario, usarlo con una contraseña nueva, comprobar que la antigua deja de valer, que todas sus sesiones se cierran y que el código no se puede reutilizar.

### Tests for User Story 8 ⚠️

- [ ] T089 [P] [US8] Test de integración del servicio en `tests/integration/test_resets_service.py`:
  - **Generación**: crea un código con `expires_at = +24 h` y solo guarda `code_hash`; generar otro pasa el anterior a `superseded`.
  - **Rechazo de la generación**: para un usuario `deactivated` se rechaza.
  - **Usuario no activo**: un código pendiente de un usuario que se desactiva queda `expired` y no se puede canjear aunque se reactive; un código de un usuario puesto en `pending_deletion` tampoco (FR-029).
  - **Auditoría**: queda `reset.created{reset_id}`.
- [ ] T090 [P] [US8] Test HTTP en `tests/integration/test_reset_http.py`:
  - **Generación**: como administrador, `POST /admin/usuarios/{id}/restablecimiento` devuelve un fragmento con el código.
  - **Canje correcto**: `POST /restablecer` con el correo, el código y una contraseña nueva válida devuelve 303 a `/login?restablecida=1`. Todas las sesiones del usuario se cierran, la contraseña antigua falla, la nueva funciona y queda `reset.used`.
  - **Rechazos**: un código usado, caducado, sustituido o de otro correo da 422 con "El código no es válido o ha caducado." y `auth.code_redeem_failed{kind:"reset"}`.
  - **Límite**: 20 fallos desde una IP la bloquean.
  - **Usuario desactivado**: con un código válido de un usuario que pasa a `deactivated` (con `status` puesto directamente, sin expirar el código), el canje da el mensaje genérico.
  - **Autorización**: un usuario normal recibe 404 en la ruta de generación.

### Implementation for User Story 8

- [ ] T091 [US8] Implementar en `src/garmin_hub/accounts/resets.py`:
  - `create_reset_code(conn, *, admin_id, user_id, keys, settings, now) -> str`, que solo admite usuarios `active`, pasa el código pendiente anterior a `superseded` en la misma transacción, inserta el nuevo y registra `reset.created`;
  - `redeem_reset_code(conn, *, email, code, new_password, keys, now) -> UUID`:
    - hace un `UPDATE` atómico de `pending` a `used`, comprobando el `user_id` del correo, `expires_at` y que `app_user.status='active'` (JOIN en la misma sentencia);
    - valida la contraseña y actualiza el hash;
    - llama a `delete_user_sessions`;
    - registra `reset.used`.
- [ ] T092 [US8] Implementar `POST /admin/usuarios/{user_id}/restablecimiento` en `src/garmin_hub/web/routes/admin.py` (409 si el usuario no está activo) y `GET /restablecer` y `POST /restablecer` en `src/garmin_hub/web/routes/reset.py`, con CSRF anónimo, límite `kind='code_redeem'` (ruta `async def` con `run_in_threadpool` y `await app.state.sleep`, R10) y mensaje genérico. Registrar el router en `src/garmin_hub/web/app.py`.
- [ ] T093 [P] [US8] Crear las plantillas `src/garmin_hub/web/templates/reset.html` y `src/garmin_hub/web/templates/admin/_reset_created.html` en español (código visible una sola vez), y añadir la acción "Generar código de restablecimiento" en `admin/_user_row.html`.

**Checkpoint**: T089–T090 en verde (paso 10 de quickstart). Las ocho historias funcionan.

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: comprobaciones transversales que exige la spec (SC-004, SC-005 y FR-034/035), documentación y validación final.

- [ ] T094 [P] Test "sin secretos en claro" en `tests/integration/test_no_plaintext_secrets.py` (SC-004):
  - ejecuta un ciclo completo con valores conocidos: `admin create`, invitación, alta, inicio de sesión, cambio de contraseña, exportación, código de restablecimiento y su canje, y borrado; las peticiones llegan desde una IP conocida (`203.0.113.57`);
  - recorre **todas** las columnas `NVARCHAR`, `VARCHAR` y `BINARY` de todas las tablas del schema de test;
  - recorre `captured_logs` y los ficheros de `settings.log_dir`;
  - en la base de datos y en los logs no aparece en claro ninguna contraseña, código, `GARMIN_HUB_SESSION_SECRET`, contraseña de `GARMIN_HUB_DB_URL`, identificador de sesión (el valor de la cookie), token CSRF ni la IP completa; en los logs, además, ningún correo.
- [ ] T095 [P] Test del catálogo de auditoría en `tests/integration/test_audit_catalog.py`:
  - cada `event_type` de `contracts/audit-events.md` se emite al menos una vez en el ciclo completo (con un paso de borrado fallido para `user.deletion_step_failed`);
  - ningún `details` contiene correos ni nombres, y ningún `ip_prefix` es una dirección completa;
  - tras borrar un usuario, sus eventos solo conservan el UUID (FR-034 y FR-035).
- [ ] T096 [P] Test de autorización general en `tests/integration/test_route_authz_matrix.py`. Recorre todas las rutas de `contracts/http.md` con cuatro principales (anónimo, usuario A, usuario B y administrador) y comprueba:
  - un anónimo recibe 303 a `/login` en las rutas autenticadas;
  - un usuario normal recibe 404 en `/admin/**`;
  - ninguna acción del usuario A cambia filas del usuario B;
  - toda petición POST sin CSRF recibe 403, y toda ruta no-GET de la app tiene `require_csrf` entre sus dependencias (recorriendo `app.routes`);
  - tras recorrer todas las rutas como usuario normal, ningún `app_user.role` ha cambiado (FR-004).
- [ ] T097 [P] Test de mensajes en español en `tests/integration/test_spanish_messages.py`:
  - los mensajes genéricos exactos de `contracts/http.md` ("Correo o contraseña incorrectos." y "El código no es válido o ha caducado.");
  - los mensajes de la política de contraseñas;
  - las páginas 404, 500 y CSRF;
  - todas las plantillas declaran `<html lang="es">`.
- [ ] T098 [P] Test de igualdad de respuestas en `tests/integration/test_login_indistinguishable.py` (SC-005): los fallos con un correo existente, un correo inexistente, un usuario desactivado y un par bloqueado producen el mismo código de estado, el mismo cuerpo (salvo el token CSRF) y la misma secuencia de llamadas de verificación argon2 (una por petición).
- [ ] T099 Revisar los textos de todas las plantillas de `src/garmin_hub/web/templates/` y de los mensajes de `src/garmin_hub/accounts/*.py` y `src/garmin_hub/security/passwords.py`: interfaz en español; identificadores, logs y commits en inglés (constitución XII).
- [ ] T100 [P] Crear `README.md` en español:
  - descripción del proyecto;
  - requisitos (Python 3.12, uv y ODBC Driver 18);
  - instalación en PowerShell y en bash;
  - variables de entorno (remitiendo a `.env.example`);
  - comandos `db upgrade`, `admin create` y `web serve`;
  - cómo ejecutar ruff, pytest y `pytest -m integration`;
  - flujo Spec Kit (constitución XIII).
- [ ] T101 [P] Actualizar `specs/001-user-access/quickstart.md` con los comandos y salidas reales tras la implementación (rutas, mensajes y códigos de salida), y corregir cualquier diferencia con `contracts/`.
- [ ] T102 Validación final: ejecutar `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` y `uv run pytest -m integration`, todos en verde. Ejecutar además `garmin-hub db upgrade`, la bajada a `base` y una nueva subida sobre una base desechable, y recorrer manualmente los pasos 0–12 de `quickstart.md` en Windows (PowerShell) y en Linux/WSL (bash), con Chrome, Edge o Firefox. Anotar el resultado en `specs/001-user-access/checklists/requirements.md`, en la sección "Notes", con los tiempos medidos de SC-001 (alta, < 2 min) y SC-007 (instalación nueva con administrador, < 5 min).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (fase 1)**: sin dependencias.
- **Foundational (fase 2)**: depende de Setup y **bloquea** todas las historias. Dentro de la fase:
  - T025 → T026 → T027 → T028, y T028 → T029;
  - T032–T034 → T035 → T036;
  - T024 depende de T022;
  - T038 depende de T020, T021, T023 y T025;
  - T040 depende de T028, T032 y T035.
- **Historias (fases 3–10)**: dependen solo de la fase 2. Gracias a `make_user` y `login_as` (T040), ninguna historia necesita otra para sus tests.
- **Polish (fase 11)**: depende de todas las historias (T094–T096 recorren el ciclo completo).

### User Story Dependencies

- **US1 (P1)**: tras la fase 2. No depende de otras historias.
- **US2 (P1)**: tras la fase 2. Usa `login_as(admin)`, no US4.
- **US3 (P1)**: tras la fase 2. Sus tests insertan la invitación directamente en `invitation` con `code_hash` (T049), sin usar el servicio de US2, para no depender de esa historia.
- **US4 (P1)**: tras la fase 2.
- **US5 (P2)**: tras la fase 2. T071 añade una ruta a `account.py` (creado en T059).
- **US6 (P2)**: tras la fase 2. T078 y T075 amplían `invitations.py`, creado en US2.
- **US7 (P2)**: tras la fase 2. T087 añade rutas a `admin.py` (creado en US2 o US6).
- **US8 (P3)**: tras la fase 2. Reutiliza `codes.py` (T049).

### Within Each User Story

- Los tests primero, y deben fallar.
- Después los servicios de `accounts/`, luego las rutas de `web/routes/` y por último las plantillas.
- En cada checkpoint, ruff limpio y tests de la historia en verde.

### Parallel Opportunities

- **Fase 1**: T003–T008 en paralelo, tras T001 y T002.
- **Fase 2**: los tests T009–T018 en paralelo; T019–T023 en paralelo; T024 y T030–T034 en paralelo, tras T022.
- **Historias**: todas las tareas de test marcadas [P] de una historia en paralelo. Con más de una persona, US1, US4, US5 y US8 tocan ficheros casi disjuntos y pueden ir a la vez.

---

## Parallel Example: User Story 4

```bash
# Tests de US4 en paralelo (escribir primero, deben fallar):
Task: "Test de integración del inicio de sesión en tests/integration/test_login_http.py"
Task: "Test de integración de la sesión en tests/integration/test_session_lifecycle.py"
Task: "Test de integración de los límites de intentos en tests/integration/test_login_ratelimit.py"

# Plantilla en paralelo con el servicio:
Task: "Crear la plantilla src/garmin_hub/web/templates/login.html"
Task: "Implementar authenticate(...) en src/garmin_hub/accounts/users.py"
```

## Parallel Example: Foundational

```bash
Task: "Test unitario de secretos y configuración en tests/unit/test_secrets_config.py"
Task: "Test unitario del filtro de logs en tests/unit/test_logging_redaction.py"
Task: "Test unitario de contraseñas en tests/unit/test_passwords.py"
Task: "Test de integración de la migración en tests/integration/test_migration_0001.py"
```

---

## Implementation Strategy

### MVP First (P1: US1–US4)

1. Fase 1 (Setup) y fase 2 (Foundational), con su checkpoint.
2. US1 → checkpoint: ya hay administrador.
3. US2 → US3 → US4, con un checkpoint tras cada una.
4. **STOP and VALIDATE**: pasos 0–7 de quickstart. Con esto ya hay una aplicación usable por invitación.

### Incremental Delivery

1. MVP P1.
2. US5 → US6 → US7, que son las P2, validando en cada checkpoint.
3. US8, la P3.
4. Fase 11 y validación final (T102).

---

## Notes

- [P] = ficheros distintos y sin dependencias pendientes.
- Cualquier cambio de esquema posterior a `0001_user_access` requiere una migración nueva con su test de subida y bajada. En esta feature no hay más cambios de esquema.
- Commit al cerrar cada tarea o grupo lógico, con mensajes en inglés.
- No se añade nada fuera de spec.md ni de plan.md. Lo de features posteriores (`key generate`, worker, `RawStore`, `can_view`) no se implementa aquí; las partes diferidas de FR-004a, FR-026, FR-028 y SC-006 están listadas en Assumptions de la spec.
