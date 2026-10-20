---

description: "Lista de tareas de la feature 002: vinculación y gestión de cuentas Garmin"
---

# Tasks: Vinculación y gestión de cuentas Garmin

**Input**: documentos de diseño de `/specs/002-garmin-account-linking/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R19), data-model.md, contracts/ (http.md, cli.md, audit-events.md, garmin-client.md), quickstart.md

**Tests**: los exigen la constitución (IX y XIII) y el flujo del proyecto. En cada historia, los tests se escriben primero y deben fallar antes de implementar.
- **Unitarios** en `tests/unit/`: sin red ni base de datos y con fixtures sintéticas.
- **Integración** en `tests/integration/` con la marca `integration`:
  - usan `FakeGarminClient`;
  - se ejecutan contra SQL Server desechable (`GARMIN_HUB_TEST_DB_URL`), o en comprobación rápida con `sqlite://`;
  - los que exigen concurrencia real llevan además `mssql`.
- **Garmin real** en `tests/live/` con la marca `live`, excluida por defecto.

**Organization**: hay una fase por historia, en el orden de prioridad de la spec:
- US1–US3 son P1;
- US4–US6 son P2;
- US7 es P3.

La fase 2 aporta lo que todas necesitan, incluida la lógica mínima de aceptación del aviso. Las fixtures `fake_garmin`, `accept_notice` y `make_garmin_account` (T031) permiten probar cada historia sin pasar por las demás.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede hacer en paralelo (ficheros distintos y sin dependencias pendientes)
- **[Story]**: historia de usuario a la que pertenece (US1…US7)
- Las rutas son relativas a la raíz del repositorio

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependencias nuevas, configuración de ejemplo y esqueleto de paquetes.

- [X] T001 Añadir a `dependencies` de `pyproject.toml` `cryptography>=44` y `garminconnect==0.3.17` (versión exacta, research R1 y R19) y regenerar `uv.lock` con `uv sync`. Comprobar que se instalan `curl_cffi`, `requests` y `ua-generator` como transitivas, y que `uv sync` funciona también en Windows (PowerShell), donde `curl_cffi` debe llegar como wheel (constitución VIII).
- [X] T002 [P] Crear el esqueleto de paquetes:
  - `src/garmin_hub/garmin/__init__.py` y `src/garmin_hub/garmin_accounts/__init__.py`;
  - la carpeta `src/garmin_hub/web/templates/garmin/`;
  - `tests/live/__init__.py`.
- [X] T003 [P] Actualizar `.env.example`:
  - Descomentar `GARMIN_HUB_MASTER_KEYS=`, con el comentario "obligatoria; formato `<versión>:<clave>[,...]`; genera una clave con `garmin-hub key generate`". Dejar `# GARMIN_HUB_RAW_DIR=` comentada, con el comentario "obligatoria desde la feature de descarga de datos" (research R5).
  - Añadir, cada una con su comentario en español: `GARMIN_HUB_GARMIN_CLIENT=garminconnect` (con la nota "`fake` solo en dev/test"), `GARMIN_HUB_GARMIN_MFA_TTL_MINUTES=5`, `GARMIN_HUB_GARMIN_MAX_ACCOUNTS=10`, `GARMIN_HUB_GARMIN_LOGIN_MAX_FAILURES=5`, `GARMIN_HUB_GARMIN_LOGIN_WINDOW_MINUTES=15`, `GARMIN_HUB_GARMIN_CHECK_INTERVAL_SECONDS=60`, `GARMIN_HUB_GARMIN_REQUEST_LEASE_SECONDS=120`, `GARMIN_HUB_GARMIN_MAX_RETRIES=2`, `GARMIN_HUB_GARMIN_LOGIN_MAX_RETRIES=0`, `GARMIN_HUB_GARMIN_LOGIN_STRATEGY_PAUSE_SECONDS=2` y `GARMIN_HUB_GARMIN_LOGIN_BUDGET_SECONDS=45`.
  - Añadir un bloque comentado con `GARMIN_HUB_LIVE_GARMIN_EMAIL` y `GARMIN_HUB_LIVE_GARMIN_PASSWORD`, con la nota "solo en la sesión de terminal para `pytest -m live`; nunca aquí".

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: cifrado y secreto obligatorio, ajustes, interfaz `GarminClient` (real y falsa), registro de MFA en memoria, migración `0002`, auditoría, autorización, candado, aviso mínimo, aplicación web, CLI `key generate` y fixtures.

**⚠️ CRITICAL**: ninguna historia empieza antes de terminar esta fase.

### Tests fundacionales (escribir primero; deben fallar)

- [X] T004 [P] Test unitario de `TokenCipher` en `tests/unit/test_token_cipher.py`:
  - cifrar y descifrar devuelve los mismos bytes;
  - `key_version` es la versión más alta configurada;
  - descifrar con la versión de la fila cuando hay varias claves;
  - versión no configurada → `UndecryptableToken`;
  - texto manipulado → `UndecryptableToken`;
  - `repr()` y `str()` de `TokenCipher` y de `GarminTokens` no contienen la clave ni el contenido.
- [X] T005 [P] Test unitario del secreto `GARMIN_HUB_MASTER_KEYS` en `tests/unit/test_secrets_config.py` (ampliar):
  - si falta, `MissingSecretsError.missing` lo incluye;
  - es inválido si:
    - el formato no es `<versión>:<clave>[,<versión>:<clave>...]`;
    - alguna versión no es un entero positivo o está repetida;
    - alguna clave no es Fernet (32 bytes en base64 url-safe);
  - si es inválido, aparece en `invalid` y el mensaje sigue contracts/cli.md sin ningún valor.
- [X] T006 [P] Test unitario de los ajustes nuevos en `tests/unit/test_secrets_config.py`:
  - los valores por defecto de data-model.md "Configuración nueva" se cargan desde `GARMIN_HUB_GARMIN_*`;
  - `GARMIN_HUB_GARMIN_CLIENT=fake` con `GARMIN_HUB_ENV=prod` → `MissingConfigError` que nombra `GARMIN_HUB_GARMIN_CLIENT` (research R18);
  - con `dev` o `test` se acepta.
- [X] T007 [P] Ampliar `tests/unit/test_cli_missing_secrets.py`: `web serve`, `db upgrade` y `admin create` sin `GARMIN_HUB_MASTER_KEYS` terminan con el código 2 y el texto `Error: faltan secretos obligatorios: GARMIN_HUB_MASTER_KEYS.` (FR-027). Con un valor inválido, el código es 2 y el mensaje de "secretos no válidos", sin el valor.
- [X] T008 [P] Test unitario de `FakeGarminClient` en `tests/unit/test_fake_garmin_client.py`: la tabla de contracts/garmin-client.md completa, incluidos:
  - `ok+<n>` y `mfa+<n>` (código `123456`);
  - `ratelimit`, `blocked`, `down`, una contraseña distinta de `correcta`, y `verify` con `profile_id >= 9000` → `TokenRejected`;
  - `script_verify(...)` y `fake.calls`;
  - un `complete_mfa` con un código incorrecto deja `pending` reutilizable.
- [X] T009 [P] Test unitario del mapeo de excepciones de `GarminConnectClient` en `tests/unit/test_garminconnect_mapping.py`:
  - **Sin red**: con un `Client` sustituido por un doble (monkeypatch del constructor en `garminconnect_client`), las excepciones sintéticas de `garminconnect` (`GarminConnectAuthenticationError`, `GarminConnectTooManyRequestsError`, el texto "All login strategies rate limited" y `GarminConnectConnectionError` con `response.status_code` 401, 403 y 503) se convierten en los errores de contracts/garmin-client.md.
  - **Respuestas no aceptadas**: un `dumps()` sin `di_refresh_token` → `GarminProtocolError`, y lo mismo un `socialProfile` sin `profileId` entero.
  - **Mensajes**: `str()` de cada error es un texto fijo que no contiene el texto de la excepción original.
  - **MFA**: `start_login` con `("needs_mfa", None)` → `MfaPending`, y `complete_mfa` llama a `resume_login(None, code)`.
  - **Recorrido de estrategias** (research R11, constitución III v1.1.0), con un doble que registra cada llamada y un `sleep` falso:
    - cada `login` se hace con `skip_strategies` = todas menos una, en el orden de R11;
    - tras un fallo genérico se pausa (2 s ±50 %) y se pasa a la siguiente;
    - un 429 → `RateLimited` y un 403 (por `response.status_code` o por el texto) → `TemporarilyBlocked`; en ambos casos no se prueba ninguna estrategia más;
    - con un reloj falso que supera los 45 s, no se prueba la siguiente estrategia y se lanza `GarminUnavailable`;
    - con `login_max_retries=1`, un 429 provoca exactamente un reintento del login completo tras el backoff; con el valor por defecto 0, ninguno.
- [X] T010 [P] Test unitario de `PendingLoginRegistry` en `tests/unit/test_pending_logins.py`:
  - alta y consulta por `attempt_id` y `user_id`;
  - otro `user_id` no lo encuentra;
  - caduca a los `mfa_ttl` con un reloj falso;
  - un intento nuevo del mismo usuario descarta el anterior y llama a `discard`;
  - el tope global de 100 lanza `RegistryFull`;
  - las entradas no contienen ningún campo con el correo ni la contraseña (se comprueba con `dataclasses.fields`).
- [X] T011 [P] Test unitario del backoff en `tests/unit/test_garmin_retry.py`:
  - los reintentos ante `RateLimited` y `GarminUnavailable` llegan como mucho a `max_retries`, con esperas base de 1 s, factor 2 y jitter de ±50 % (con `random` sembrado y un `sleep` falso que registra);
  - `TokenRejected` y `GarminProtocolError` no se reintentan (research R11).
- [X] T012 [P] Test unitario de estructura en `tests/unit/test_garmin_import_guard.py`: recorre con `ast` todos los `.py` de `src/garmin_hub/` y falla si algún módulo distinto de `src/garmin_hub/garmin/garminconnect_client.py` importa `garminconnect` o `curl_cffi` (constitución III, research R1).
- [X] T013 [P] Ampliar `tests/unit/test_logging_redaction.py`:
  - tras `configure_logging`, los loggers `garminconnect` y `curl_cffi` están en `ERROR`;
  - un `logging.getLogger("garminconnect").error(...)` con un correo, una contraseña, un token y un `profileId` centinela en `msg`, en `args` y en `exc_info` no deja ningún centinela en el fichero JSON, y deja el texto fijo `third-party library error (details suppressed)` (research R17).
- [X] T014 [P] Test de integración de la migración en `tests/integration/test_migration_0002.py`:
  - `upgrade head` crea `garmin_account`, `garmin_token`, `data_notice_acceptance` y `garmin_login_failure` con las columnas de data-model.md;
  - `downgrade 0001_user_access` las elimina y deja intactas las tablas de 001;
  - un nuevo `upgrade` funciona.
  - Con la marca `mssql`, además:
    - `CK_garmin_account_status_fields` rechaza `status='error'` sin `error_code`, `status='unlinked'` sin `unlinked_at` y `status='deleting'` sin `deletion_requested_at`;
    - los tres índices únicos filtrados de R7 rechazan duplicados en estados activos y los permiten si una de las filas está en `deleting`, o en `unlinked` para `UX_garmin_account_profile_active`.
- [X] T015 [P] Ampliar `tests/integration/test_audit_catalog.py`: los once eventos `garmin.*` de contracts/audit-events.md están en `ALLOWED_DETAILS` con exactamente sus claves, y `record_event` rechaza cualquier otra clave.

### Implementación fundacional

- [X] T016 Implementar `src/garmin_hub/security/token_cipher.py` (research R5):
  - `parse_master_keys(raw: str) -> dict[int, Fernet]`, que lanza `ValueError` sin incluir valores;
  - `TokenCipher` con `current_version`, `encrypt(data: bytes) -> tuple[bytes, int]` y `decrypt(ciphertext: bytes, key_version: int) -> bytes`; este último lanza `UndecryptableToken` si la versión no está configurada o ante `InvalidToken`;
  - `__repr__` enmascarado.
- [X] T017 Ampliar `src/garmin_hub/secrets.py`:
  - `REQUIRED_SECRETS` incluye `GARMIN_HUB_MASTER_KEYS`;
  - `Secrets.master_keys: str` con `field(repr=False)`;
  - `load_secrets` valida el secreto con `parse_master_keys` y, si no es válido, lo añade a `invalid`;
  - `MissingSecretsError.message` incluye el texto de contracts/cli.md para `GARMIN_HUB_MASTER_KEYS`.
- [X] T018 [P] Ampliar `Settings` en `src/garmin_hub/config.py` con `garmin_client: Literal["garminconnect", "fake"] = "garminconnect"`, `garmin_mfa_ttl_minutes: int = 5`, `garmin_max_accounts: int = 10`, `garmin_login_max_failures: int = 5`, `garmin_login_window_minutes: int = 15`, `garmin_check_interval_seconds: int = 60`, `garmin_request_lease_seconds: int = 120`, `garmin_max_retries: int = 2`, `garmin_login_max_retries: int = 0`, `garmin_login_strategy_pause_seconds: float = 2` y `garmin_login_budget_seconds: float = 45`. Un `model_validator` rechaza `fake` si `env == "prod"`, y `load_settings` lo convierte en `MissingConfigError(["GARMIN_HUB_GARMIN_CLIENT"])` con el mensaje de contracts/cli.md.
- [X] T019 [P] Ampliar `configure_logging` en `src/garmin_hub/logging_setup.py`: poner `logging.getLogger("garminconnect")` y `logging.getLogger("curl_cffi")` en `ERROR`, con el filtro `ThirdPartyLogScrubber`. Este filtro sustituye `msg` por `"third-party library error (details suppressed)"` y vacía `args`, `exc_info` y `stack_info`; después se aplica `RedactingFilter` (research R17).
- [X] T020 Implementar `src/garmin_hub/garmin/client.py` según contracts/garmin-client.md:
  - las dataclasses congeladas `GarminTokens`, `GarminIdentity`, `LoginSucceeded`, `MfaPending` y `VerifyResult`; `GarminTokens.value` y `GarminIdentity.profile_id` llevan `field(repr=False)`;
  - el `Protocol` `GarminClient` con `start_login`, `complete_mfa`, `discard` y `verify`;
  - los errores `GarminError` → `InvalidCredentials`, `InvalidMfaCode`, `RateLimited`, `TemporarilyBlocked`, `GarminUnavailable`, `TokenRejected` y `GarminProtocolError`, cada uno con un mensaje fijo en inglés.
- [X] T021 [P] Implementar `src/garmin_hub/garmin/retry.py`: `call_with_backoff(fn, *, max_retries, sleep, rng)`, que reintenta solo `RateLimited` y `GarminUnavailable` con la regla de R11.
- [X] T022 [P] Implementar `src/garmin_hub/garmin/fake.py`: `FakeGarminClient` con la tabla de contracts/garmin-client.md, `script_verify(profile_id, outcome)`, `calls: list[tuple[str, ...]]` (sin la contraseña: registra solo el nombre de la operación y el correo) y tokens deterministas `b'{"fake":<n>,"rev":<k>}'`.
- [X] T023 Implementar `src/garmin_hub/garmin/garminconnect_client.py` (research R1, R4, R5 y R10; contracts/garmin-client.md):
  - `GarminConnectClient(max_retries, sleep)` crea una instancia nueva de `garminconnect.client.Client` por login y por verificación; nunca usa `garminconnect.Garmin`;
  - `GarminConnectClient(max_retries, login_max_retries, strategy_pause, login_budget, sleep, clock, rng)`;
  - `start_login`, que recorre las estrategias de R11 una a una (con `skip_strategies`, pausa con jitter, corte ante 429 o 403, tiempo máximo y reintentos configurables);
  - `complete_mfa` (`resume_login(None, code)`);
  - `discard` hace `client._clear_auth_state()` dentro de `contextlib.suppress`;
  - `verify` con `loads`, `connectapi("/userprofile-service/socialProfile")` y la comparación de `dumps()` para detectar la renovación, envuelto en `call_with_backoff`;
  - la función `_map_exception` concentra el mapeo de errores.
- [X] T024 [P] Implementar `src/garmin_hub/garmin/pending.py`:
  - la dataclass `PendingLogin` con `attempt_id`, `user_id`, `purpose: Literal["link","reauth"]`, `garmin_account_id: UUID | None`, `alias: str | None`, `expires_at`, `mfa_failures: int` y `pending: MfaPending`;
  - `PendingLoginRegistry(ttl, clock, client, max_entries=100)` con `add`, `get(attempt_id, user_id)`, `pop`, `discard_for_user` y `discard_for_account`;
  - un `threading.Lock`, purga en cada llamada y un `discard` en el cliente al expulsar una entrada (research R3).
- [X] T025 Añadir a `src/garmin_hub/db/schema.py` las cuatro tablas de data-model.md:
  - **`garmin_account`**:
    - `alias NVARCHAR(50) NOT NULL`, `alias_key NVARCHAR(50) NOT NULL`, `garmin_profile_id BIGINT NOT NULL`;
    - `status VARCHAR(20) NOT NULL CHECK IN ('valid','reauth_required','error','unlinked','deleting')`;
    - `error_code VARCHAR(32) NULL CHECK IN ('token_undecryptable','identity_mismatch')`;
    - `CK_garmin_account_status_fields`, que exige `error_code` NOT NULL si y solo si `status='error'`, `unlinked_at` NOT NULL si `status='unlinked'` y `deletion_requested_at` NOT NULL si `status='deleting'`;
    - los índices `UX_garmin_account_profile_active`, `UX_garmin_account_user_profile` y `UX_garmin_account_user_alias`, con `mssql_where` y `sqlite_where` y los filtros literales de data-model.md, más `IX_garmin_account_user`.
  - **`garmin_token`**: `ciphertext VARBINARY(MAX) NOT NULL` y `key_version INT NOT NULL CHECK > 0`.
  - **`data_notice_acceptance`**: con la PK `(user_id, notice_version)` y `notice_version > 0`.
  - **`garmin_login_failure`**: `BigIdentity` e `IX_garmin_login_failure_user`.
  - **Claves ajenas**: todas `NO ACTION`.
- [X] T026 Crear la migración `src/garmin_hub/db/migrations/versions/0002_garmin_accounts.py` (`revision = "0002_garmin_accounts"`, `down_revision = "0001_user_access"`). Debe crear exactamente el esquema de T025 en el schema configurado, con los índices filtrados, y su `downgrade` debe borrarlo en orden inverso. Comprobar con `render_sql` que el SQL de SQL Server de los índices lleva `WHERE`.
- [X] T027 [P] Ampliar `ALLOWED_DETAILS` en `src/garmin_hub/accounts/audit.py` con los once eventos `garmin.*` y sus claves exactas de contracts/audit-events.md.
- [X] T028 Crear el dominio base en `src/garmin_hub/garmin_accounts/`. Todos los textos de usuario van en español, y en `accounts.py` las consultas filtran siempre por `garmin_account_id` **y** `user_id` (R15).
  - **`errors.py`**: `message_for(error)` y `reason_for(error)` según la tabla de research R10, más las constantes `MSG_*` de R6, R7, R9 y R10.
  - **`notice.py`**: `NOTICE_VERSION = 1`, `has_accepted_current(conn, user_id)` y `accept(conn, user_id, now, ip_prefix)`. `accept` es idempotente y audita `garmin.notice_accepted` solo si inserta.
  - **`lease.py`** (R6):
    - `acquire(conn, account_id, now, seconds) -> bool` y `release(conn, account_id)`, con un `UPDATE` condicional;
    - `claim_check(conn, account_id, now, interval) -> bool`.
  - **`accounts.py`, escritura condicional** (R6): `update_if_active(conn, account_id, values) -> bool` hace `UPDATE garmin_account ... WHERE garmin_account_id = ? AND status IN ('valid','reauth_required','error')` y devuelve si ha afectado a una fila. `save_token` solo se llama si ha devuelto `True`.
  - **`accounts.py`**:
    - `AccountRow`;
    - `parse_account_id(raw: str) -> UUID | None`;
    - `get_own_account(conn, user_id, account_id) -> AccountRow | None`;
    - `normalize_alias(alias) -> tuple[str, str]`, que valida de 1 a 50 caracteres sin espacios alrededor;
    - `count_active(conn, user_id)` y `save_token(conn, account_id, tokens, cipher, now)`;
    - `load_tokens(conn, account_id, cipher)`, que lanza `UndecryptableToken`.
- [X] T029 Ampliar `create_app` en `src/garmin_hub/web/app.py`:
  - Debe recibir `garmin_client: GarminClient | None = None`. Por defecto usa `FakeGarminClient` si `settings.garmin_client == "fake"`; si no, `GarminConnectClient`.
  - Añadir a `app.state`: `token_cipher = TokenCipher(parse_master_keys(secrets.master_keys))`, `garmin_client`, `pending_logins = PendingLoginRegistry(...)` y `rng`.
  - Registrar el módulo `garmin_hub.web.routes.garmin_accounts` en `route_modules()`.
  - Crear `src/garmin_hub/web/routes/garmin_accounts.py` con:
    - `router = APIRouter(prefix="/cuentas-garmin", dependencies=[Depends(require_csrf)])`;
    - un helper `own_account_or_404(conn, user, raw_id)` que da la misma respuesta 404 en los tres casos de R15.
  - Añadir `require_regular_user` en `src/garmin_hub/web/deps.py`: 404 si `role == "admin"`.
- [X] T030 [P] Añadir `key generate` a `src/garmin_hub/cli/main.py`, según contracts/cli.md: no carga secretos, imprime `Fernet.generate_key()` y la línea de ayuda, y termina con 0. Test en `tests/unit/test_cli_key_generate.py`: la salida es una clave Fernet válida y el comando funciona con un entorno vacío.
- [X] T031 Ampliar las fixtures de `tests/conftest.py` y `tests/integration/conftest.py`:
  - **Secretos**: el fixture de secretos incluye `GARMIN_HUB_MASTER_KEYS=1:<clave de test generada>`.
  - **`fake_garmin`**: un `FakeGarminClient` nuevo por test, pasado a `create_app`.
  - **`pending_logins`**: acceso a `app.state.pending_logins`.
  - **`accept_notice(user_id)`**: inserta `(user_id, NOTICE_VERSION)`.
  - **`make_garmin_account(user_id, *, alias, profile_id, status="valid", with_token=True, ...)`**: inserta directamente la fila y el token cifrado con `app.state.token_cipher`.
  - **Limpieza**: añadir `garmin_token`, `garmin_account`, `data_notice_acceptance` y `garmin_login_failure` al principio de `TABLES_CHILD_FIRST`.

**Checkpoint**: `uv run ruff check` limpio; T004–T015 en verde; `garmin-hub db upgrade` llega a `0002_garmin_accounts`; la aplicación arranca con el cliente falso.

---

## Phase 3: User Story 1 - Vincular una cuenta Garmin (Priority: P1) 🎯 MVP

**Goal**: un usuario normal que ha aceptado el aviso vincula una cuenta con alias, correo y contraseña, y con MFA si Garmin lo pide. Solo se guardan el acceso cifrado y el `profileId`.

**Independent Test**: con `accept_notice` y `fake_garmin`, vincular `ok+1@example.test` y `mfa+2@example.test` (código `123456`) y comprobar que ambas quedan `valid` con su token cifrado, y que en ninguna tabla aparecen la contraseña ni el correo.

### Tests for User Story 1 ⚠️

- [X] T032 [P] [US1] Test de integración en `tests/integration/test_garmin_link_http.py`:
  - **Vinculación correcta**: `POST /cuentas-garmin/vincular` con `ok+1@example.test` / `correcta` → `303 → /cuentas-garmin?vinculada=1`. La fila queda en `status='valid'`, con `last_login_at = now`, `last_sync_at` NULL y un `garmin_token` cuya `key_version` es la vigente (US1-1).
  - **Errores de Garmin**: `mala` → 422 con "Garmin no acepta ese correo o contraseña." y ninguna fila creada (US1-5). `down`, `ratelimit` y `blocked` → 422 con los tres mensajes de R10.
  - **Alias**: vacío o de 51 caracteres → 422 sin llamar a Garmin (`fake.calls` vacío).
  - **Duplicados**: la misma identidad del mismo usuario → 422 con «alias» (US1-7). La misma identidad de otro usuario → 422 con un mensaje que no contiene ni el nombre ni el correo del otro (US1-6). Un alias repetido sin distinguir mayúsculas → 422.
  - **Máximo de cuentas**: con 10 cuentas activas, la siguiente da 409 y las `unlinked` no cuentan (R8).
  - **Administrador**: recibe 404 en `GET` y `POST` (US1-8).
  - **Datos sensibles**: el cuerpo de ninguna respuesta contiene la contraseña ni el correo enviados.
- [X] T033 [P] [US1] Test de integración en `tests/integration/test_garmin_link_mfa.py`:
  - `mfa+2@example.test` → 200 con la página del código y un `attempt_id` oculto;
  - `000000` → 422 "El código de verificación no es correcto." y sigue vivo;
  - `123456` → 303, cuenta `valid` y el registro vacío (US1-2, US1-4);
  - avanzar el reloj 5 minutos y 1 segundo → 410 "El intento ha caducado; vuelve a empezar." (US1-3);
  - `mfa/cancelar` descarta el intento;
  - el `attempt_id` de otro usuario → 410;
  - empezar otro intento descarta el primero;
  - con el registro lleno → mensaje de "no disponible".
- [X] T034 [P] [US1] Test de integración en `tests/integration/test_garmin_link_ratelimit.py`:
  - 5 fallos de credenciales o de MFA en 15 minutos → el sexto intento da 429 "Has hecho demasiados intentos con Garmin; espera unos minutos." sin ninguna llamada nueva en `fake.calls`;
  - los errores transitorios y los locales no cuentan;
  - pasada la ventana, vuelve a permitirse (FR-010, R9).
- [X] T035 [P] [US1] Test de integración en `tests/integration/test_garmin_link_audit.py`:
  - una vinculación correcta registra `garmin.account_linked` con `{"garmin_account_id", "recovered": false, "mfa": bool}`;
  - cada fallo registra `garmin.link_failed` con su `reason` de contracts/audit-events.md;
  - ningún `details` contiene el alias, el correo, el `profileId` ni la contraseña (FR-028).
- [X] T036 [P] [US1] Test de concurrencia en `tests/integration/test_garmin_link_concurrency.py` (marcas `integration` y `mssql`): dos usuarios vinculan a la vez la misma identidad, cada uno en su hilo con su propia conexión. Exactamente uno obtiene una cuenta `valid` y el otro el mensaje de "ya vinculada a otro usuario" (caso límite y R7).

### Implementation for User Story 1

- [X] T037 [US1] Implementar `src/garmin_hub/garmin_accounts/ratelimit.py`: `is_blocked(conn, user_id, now, max_failures, window)`, `record_failure(conn, user_id, now)` y `purge_old(conn, now)` (más de 24 horas), sobre `garmin_login_failure` (R9).
- [X] T038 [US1] Implementar en `src/garmin_hub/garmin_accounts/accounts.py` el servicio de vinculación (R7, R8, R12):
  - **`start_link(engine, client, registry, cipher, settings, user, alias, email, password, now, ip_prefix) -> Linked | NeedsMfa`**, en este orden:
    1. validar el alias;
    2. comprobar el límite de R9 y el máximo de cuentas;
    3. llamar a `client.start_login` fuera de cualquier transacción;
    4. con `MfaPending`, guardar el intento en el registro y devolver `NeedsMfa(attempt_id)`;
    5. con `LoginSucceeded`, llamar a `_persist_link`.
  - **`complete_link_mfa(...)`**: recupera el intento con `get(attempt_id, user_id)` y llama a `client.complete_mfa`. Con `InvalidMfaCode`, anota el fallo (`record_failure` y `mfa_failures`) y deja el intento vivo.
  - **`_persist_link`**:
    1. en una transacción con `lock_user`, comprueba la identidad propia activa (`already_linked_self`);
    2. revalida el alias y el máximo;
    3. inserta `garmin_account` y `garmin_token` con `save_token`;
    4. si hay `IntegrityError` de `UX_garmin_account_profile_active`, devuelve `linked_elsewhere`.
  - **Recuperación**: deja el gancho `recover_if_unlinked` como `return None`; lo completa T059.
  - **Auditoría**: según T035.
  - **Datos sensibles**: nunca pasa el correo ni la contraseña a ningún log ni a ninguna excepción propia.
- [X] T039 [US1] Implementar en `src/garmin_hub/web/routes/garmin_accounts.py` las rutas de contracts/http.md:
  - `GET /vincular` y `POST /vincular` (con la puerta del aviso de T028: si no se ha aceptado, `303 → /cuentas-garmin/aviso?next=/cuentas-garmin/vincular`);
  - `POST /mfa` y `POST /mfa/cancelar`.
  - Todas con `require_regular_user`. Los códigos son 422, 409, 410 y 429 según el contrato, y el formulario solo conserva `alias`.
- [X] T040 [P] [US1] Crear las plantillas en `src/garmin_hub/web/templates/garmin/`:
  - `link.html`: alias, correo y contraseña de Garmin con `autocomplete="off"` en el correo y `new-password` en la contraseña, y una explicación de que la contraseña no se guarda;
  - `mfa.html`: código, `attempt_id` oculto, tiempo restante y botón "Cancelar".
  - Textos en español.
- [X] T041 [US1] Añadir el enlace "Mis cuentas Garmin" en `src/garmin_hub/web/templates/base.html`, solo para `role == 'user'` (contracts/http.md, "Cambios en rutas de 001").

**Checkpoint**: T032–T036 en verde (T036 solo en SQL Server); pasos 3–8 de quickstart con el cliente falso.

---

## Phase 4: User Story 2 - Ver mis cuentas Garmin (Priority: P1)

**Goal**: el usuario ve el listado de sus cuentas con su estado y sus fechas, y un aviso en la página de inicio si alguna necesita atención.

**Independent Test**: con `make_garmin_account` en los cinco estados, abrir `/cuentas-garmin` y `/` y comprobar las etiquetas, las fechas y los avisos.

### Tests for User Story 2 ⚠️

- [X] T042 [P] [US2] Test de integración en `tests/integration/test_garmin_list_http.py`:
  - **Dos cuentas**: se ven con alias, etiqueta, último login, "Nunca" en la sincronización y la última comprobación (US2-1).
  - **Cuentas que necesitan atención**: `reauth_required` muestra la acción "Reautenticar" destacada, y `error` muestra su motivo de R10 (US2-2).
  - **Sin cuentas**: muestra el mensaje y el enlace para vincular (US2-3).
  - **Desvinculada**: `unlinked` aparece como "Desvinculada (datos conservados)" con "Borrar datos" (US2-4).
  - **Borrado incompleto**: `deleting` aparece como "Borrando datos… (no se pudo completar)" con "Reintentar".
  - **Mensajes de resultado**: los parámetros `?vinculada=1`, `?recuperada=1`, `?reautenticada=1`, `?desvinculada=1` y `?borrada=1` muestran su mensaje.
- [X] T043 [P] [US2] Test de integración en `tests/integration/test_garmin_home_notices.py`:
  - con una cuenta en `reauth_required` y otra en `error`, `/` muestra el aviso con los dos alias y sus enlaces; con todas en `valid`, `unlinked` o `deleting`, no lo muestra (US2-5, FR-016a);
  - un administrador no ve ningún aviso.

### Implementation for User Story 2

- [X] T044 [US2] Añadir `list_accounts(conn, user_id) -> list[AccountRow]` (ordenado por `created_at`) y `accounts_needing_attention(conn, user_id)` (los estados `reauth_required` y `error`) en `src/garmin_hub/garmin_accounts/accounts.py`.
- [X] T045 [US2] Implementar `GET /cuentas-garmin` en `src/garmin_hub/web/routes/garmin_accounts.py`, con los mensajes de resultado de T042.
- [X] T046 [P] [US2] Crear `src/garmin_hub/web/templates/garmin/list.html` y `src/garmin_hub/web/templates/garmin/_row.html`, con las etiquetas y acciones de la tabla "Etiquetas de estado en la interfaz" de contracts/http.md. Las fechas usan el filtro de fecha de 001 (`%Y-%m-%d %H:%M UTC`). `last_sync_at` y `last_checked_at` muestran "Nunca" si son NULL.
- [X] T047 [US2] Ampliar `home` en `src/garmin_hub/web/routes/account.py` y `src/garmin_hub/web/templates/home.html` con el aviso (1) de contracts/http.md, solo para `role == 'user'`.

**Checkpoint**: T042–T043 en verde; paso 1 de quickstart.

---

## Phase 5: User Story 3 - Solo veo y gestiono mis propias cuentas (Priority: P1)

**Goal**: ningún usuario, ni el administrador, puede ver ni tocar cuentas ajenas, y la respuesta no deja distinguir "no existe" de "no es tuya".

**Independent Test**: con los usuarios A y B y un administrador, recorrer todas las rutas `{account_id}` del router y comparar el estado y el cuerpo de la respuesta.

### Tests for User Story 3 ⚠️

- [X] T048 [P] [US3] Test de integración en `tests/integration/test_garmin_authz_matrix.py`:
  - **Recorrido**: recorre dinámicamente `garmin_accounts.router.routes` y, para cada ruta con `{account_id}` y cada método, prueba como A cuatro casos:
    - el id de una cuenta de B;
    - un UUID inexistente;
    - `abc`;
    - un UUID en mayúsculas de B.
  - **Respuesta**: los cuatro dan 404 con un cuerpo idéntico, sin cambios en la base de datos y sin llamadas en `fake.calls` (US3-2, SC-004).
  - **Listado**: el de A no contiene ningún alias de B (US3-1).
  - **Administrador**: recibe 404 en todas las rutas del router, también en `GET /cuentas-garmin` y en `/aviso` (US3-3, FR-015).
  - **Sin sesión**: `303 → /login`.
  - **CSRF**: todo POST sin CSRF da 403. Este caso queda cubierto por el `test_route_authz_matrix.py` de 001 vía `route_modules()`; comprobarlo.

### Implementation for User Story 3

- [X] T049 [US3] Revisar que todas las rutas con `{account_id}` de `src/garmin_hub/web/routes/garmin_accounts.py` usan `own_account_or_404` antes de cualquier otra lógica, y que `require_regular_user` está declarado a nivel de router. Corregir lo que falle en T048. Las rutas que añaden las fases siguientes heredan la matriz automáticamente.

**Checkpoint**: T048 en verde; paso 10 de quickstart. **MVP P1 completo**: para usuarios reales hace falta además la página del aviso (US6, T065–T066).

---

## Phase 6: User Story 4 - Reautenticar una cuenta caducada (Priority: P2)

**Goal**: una cuenta en `reauth_required`, `error` o `valid` se reautentica con correo y contraseña, y con MFA si se pide, y conserva su identificador, su alias y sus datos.

**Independent Test**: con `make_garmin_account(status="reauth_required", profile_id=7)`, reautenticar con `ok+7@example.test` y comprobar que queda `valid` con el mismo `garmin_account_id` y un token nuevo.

### Tests for User Story 4 ⚠️

- [X] T050 [P] [US4] Test de integración en `tests/integration/test_garmin_reauth_http.py`:
  - **Desde `reauth_required`**: `POST /{id}/reautenticar` → `303 ?reautenticada=1`. La cuenta queda `valid`, con el mismo id y alias, un `garmin_token.issued_at` nuevo y `last_login_at` actualizado (US4-1).
  - **Desde otros estados**: desde `error` queda `valid` y `error_code` NULL. Desde `valid` también se permite (US4-4).
  - **MFA**: con `mfa+7@example.test`, la página del código y `123456` → `valid`.
  - **Identidad distinta**: `ok+8@example.test` → 422 "Esas credenciales son de otra cuenta Garmin distinta de «alias».". El estado y el token no cambian, y no cuenta para R9 (US4-2).
  - **Varias cuentas**: con otra cuenta del mismo usuario, esa sigue igual (US4-3).
  - **Estados no permitidos**: `unlinked` y `deleting` → 409.
  - **Candado**: con `request_lease_until` en el futuro → 409 "Hay otra operación en curso con esta cuenta; inténtalo en unos segundos.", y tras el intento el candado se libera.
  - **Límites**: aplica R9.
  - **Auditoría**: `garmin.reauthenticated` y `garmin.reauth_failed` con su `reason`.

### Implementation for User Story 4

- [X] T051 [US4] Implementar en `src/garmin_hub/garmin_accounts/accounts.py`:
  - **`start_reauth(...)`**:
    1. `get_own_account`;
    2. un estado de los permitidos por FR-018;
    3. R9;
    4. `acquire` del candado;
    5. `client.start_login` fuera de la transacción;
    6. `release` en un `finally`.
  - **`complete_reauth_mfa(...)`**: lo mismo con `complete_mfa`.
  - **`_persist_reauth`**:
    - compara `identity.profile_id` con `garmin_profile_id`; si es distinta, `identity_mismatch` sin cambios;
    - si coincide, pone `status='valid'`, `error_code` NULL y `last_login_at` con `update_if_active`, y solo si ha afectado a una fila reemplaza el token con la clave vigente y audita;
    - si no ha afectado a ninguna fila (la cuenta se desvinculó mientras tanto), descarta los accesos y devuelve el mensaje de R6.
  - **MFA pendiente**: se guarda con `purpose="reauth"` y `garmin_account_id`.
- [X] T052 [US4] Implementar `GET /{account_id}/reautenticar` y `POST /{account_id}/reautenticar` en `src/garmin_hub/web/routes/garmin_accounts.py`. Ampliar `POST /mfa` para enrutar por `purpose` y redirigir a `?reautenticada=1`.
- [X] T053 [P] [US4] Crear `src/garmin_hub/web/templates/garmin/reauth.html`: correo y contraseña, el alias como contexto, y el texto "Introduce las credenciales de la misma cuenta Garmin".

**Checkpoint**: T050 en verde.

---

## Phase 7: User Story 5 - Desvincular una cuenta (Priority: P2)

**Goal**: desvincular conservando o borrando los datos. El borrado es reanudable, las cuentas conservadas se pueden recuperar, y el borrado del usuario arrastra sus cuentas.

**Independent Test**: desvincular una cuenta con "borrar" y comprobar que no queda nada de ella. Desvincular otra con "conservar", comprobar que no queda su token y que se recupera al vincularla de nuevo.

### Tests for User Story 5 ⚠️

- [X] T054 [P] [US5] Test de integración en `tests/integration/test_garmin_unlink_http.py`:
  - **Página de confirmación**: `GET /{id}/desvincular` explica las dos opciones e incluye el aviso sobre los entrenadores con consentimiento (US5-1, FR-023).
  - **Validación**: sin `mode`, o con una confirmación distinta del alias → 422 sin cambios.
  - **`mode=keep`**: borra `garmin_token`, deja `unlinked` con `unlinked_at` y descarta el MFA pendiente de esa cuenta (US5-3, FR-021).
  - **`mode=delete`**: no queda ni la fila ni el token (US5-2, SC-005).
  - **Candado**: con `request_lease_until` en el futuro, `desvincular` y `borrar-datos` → 409 sin cambios.
  - **Carrera** (R6, FR-021): se desvincula entre la llamada a Garmin y la escritura de una reautenticación, con un `FakeGarminClient` cuyo `start_login` ejecuta `unlink` antes de devolver. La cuenta queda `unlinked` y sin `garmin_token`.
  - **Borrado posterior**: `GET` y `POST /{id}/borrar-datos` sobre una `unlinked` → borrada (US5-5), y 409 si no está `unlinked`.
  - **Auditoría**: `garmin.account_unlinked` con `data` = `kept` o `deleted`, `garmin.data_deletion_requested` y `garmin.account_deleted`.
- [X] T055 [P] [US5] Test de integración en `tests/integration/test_garmin_recover.py`:
  - **Recuperación**: A desvincula `profile_id=5` conservando los datos y lo vincula de nuevo con otro alias → `303 ?recuperada=1`. Mismo `garmin_account_id`, alias original, `valid`, token nuevo y `garmin.account_linked` con `recovered: true` (US5-4).
  - **Otro usuario**: con la de A en `unlinked`, B vincula la misma identidad y obtiene un `garmin_account_id` distinto, sin acceso a la de A (US5-7). Si después A intenta recuperarla, se rechaza con "ya vinculada a otro usuario" (US5-4, FR-007).
  - **Máximo de cuentas**: la recuperación cuenta para el máximo (R8).
- [X] T056 [P] [US5] Test de integración en `tests/integration/test_garmin_account_deletion_resume.py`:
  - **Fallo y reintento**: con un paso registrado de prueba (orden 500) que falla la primera vez, `mode=delete` deja la cuenta en `deleting` con `deletion_requested_at` y registra `garmin.account_deletion_step_failed`. El listado muestra "Reintentar", y `POST /{id}/reintentar-borrado` completa el borrado sin dejar filas huérfanas (US5-6, FR-022).
  - **Estado incorrecto**: `reintentar-borrado` sobre una cuenta que no está en `deleting` → 409.
  - **Pasos repetidos**: ejecutar dos veces cada paso no da error (idempotencia).
- [X] T057 [P] [US5] Test de integración en `tests/integration/test_garmin_user_deletion.py`:
  - **Borrado propio**: con dos cuentas (una `valid` y una `unlinked`), aceptaciones y fallos de login, `POST /cuenta/eliminar` deja sin filas a ese usuario en `garmin_account`, `garmin_token`, `data_notice_acceptance` y `garmin_login_failure`. El `user.deleted` lista el paso `garmin_accounts` (FR-029).
  - **Borrado por el administrador**: lo mismo por el flujo de 001.

### Implementation for User Story 5

- [X] T058 [US5] Implementar `src/garmin_hub/garmin_accounts/deletion.py` (R14):
  - **Registro**: `AccountDeletionContext(engine, now)`, `register_account_deletion_step(name, order, fn)` y `registered_account_steps()`, con los pasos `garmin_token` (orden 10) y `garmin_account_row` (orden 1000).
  - **`unlink(...)`**: primero reclama el candado (`acquire`); si no puede, lanza `Busy` (409).
    - con `mode=keep`: en una transacción, borra el token, pasa a `unlinked`, pone `unlinked_at`, libera el candado y audita; después llama a `registry.discard_for_account`;
    - con `mode=delete`: en una transacción, borra el token, pasa a `deleting`, pone `deletion_requested_at` y audita; después llama a `run_account_deletion`.
  - **Borrado posterior**: `request_data_deletion(...)` (`unlinked → deleting`), también con el candado.
  - **`run_account_deletion(ctx, account_id, ip_prefix)`**: ejecuta los pasos en orden, registra `garmin.account_deletion_step_failed` o `garmin.account_deleted`, y lanza `StepFailed`.
  - **Borrado del usuario**: `register_deletion_step("garmin_accounts", 50, ...)` de 001, que borra cada cuenta del usuario y después sus filas de `data_notice_acceptance` y `garmin_login_failure`. Se registra al importar el módulo, y se importa desde `create_app`.
- [X] T059 [US5] Completar en `src/garmin_hub/garmin_accounts/accounts.py` la recuperación de `_persist_link` (R7, paso 3):
  - si el usuario tiene la identidad en `unlinked`, revalidar el máximo de R8 y reactivar la fila: `status='valid'`, `unlinked_at` NULL, token nuevo y `last_login_at`;
  - si la actualización viola `UX_garmin_account_profile_active`, devolver `linked_elsewhere`;
  - devolver `recovered=True`.
- [X] T060 [US5] Implementar en `src/garmin_hub/web/routes/garmin_accounts.py`:
  - `GET /{account_id}/desvincular` y `POST /{account_id}/desvincular`;
  - `GET /{account_id}/borrar-datos` y `POST /{account_id}/borrar-datos`;
  - `POST /{account_id}/reintentar-borrado`.
  - Todas según contracts/http.md. La confirmación compara con el alias sin distinguir mayúsculas.
- [X] T061 [P] [US5] Crear `src/garmin_hub/web/templates/garmin/unlink.html` y `src/garmin_hub/web/templates/garmin/delete_data.html`. `unlink.html` lleva las opciones "Conservar datos" y "Borrar datos", el aviso de FR-023 y el campo para escribir el alias.

**Checkpoint**: T054–T057 en verde; pasos 12–14 de quickstart.

---

## Phase 8: User Story 6 - Aceptar el aviso de datos antes de vincular (Priority: P2)

**Goal**: el aviso versionado se muestra y se acepta antes de vincular o reautenticar, y la página de inicio avisa cuando hay una versión nueva pendiente.

**Independent Test**: sin aceptación, intentar vincular y ser redirigido; aceptar y comprobar la fila `(user_id, NOTICE_VERSION)`; subir `NOTICE_VERSION` en el test y comprobar que se pide otra vez.

### Tests for User Story 6 ⚠️

- [X] T062 [P] [US6] Test de integración en `tests/integration/test_garmin_notice_http.py`:
  - **Redirección al aviso**: sin aceptación, `GET /vincular` da `303 → /cuentas-garmin/aviso?next=/cuentas-garmin/vincular` y `POST /vincular` también, sin llamar a Garmin (US6-1, SC-006).
  - **Validación de `next`**: `POST /aviso` sin `accept` → 422. Con `accept=1` → 303 a `next`. Un `next` externo (`https://evil.test`, `//evil.test`) o fuera de `/cuentas-garmin` → `/cuentas-garmin`.
  - **Registro**: queda la fila con `accepted_at` y `garmin.notice_accepted`. Repetir no duplica ni audita de nuevo (US6-2).
  - **Versión nueva**: con `NOTICE_VERSION` parcheado a 2, vincular y reautenticar vuelven a pedir el aviso (US6-3).
  - **Contenido**: el texto menciona actividades, recorridos GPS y datos de salud, "solo tú y los entrenadores a los que des consentimiento", que el administrador no puede verlos, y que se puede desvincular y borrar (US6-4, FR-011).
- [X] T063 [P] [US6] Test de integración en `tests/integration/test_garmin_home_notices.py` (ampliar):
  - **Con cuentas vinculadas**: si hay una cuenta `valid` y `NOTICE_VERSION` está parcheado a 2 sin aceptar, `/` muestra "Hay una versión nueva del aviso de datos" con su enlace, y la cuenta sigue `valid` (US6-5, FR-012).
  - **Sin cuentas vinculadas**: sin cuentas, o solo con cuentas `unlinked`, no se muestra.
- [X] T064 [P] [US6] Test unitario en `tests/unit/test_notice_template.py`: existe `src/garmin_hub/web/templates/garmin/notice_v{NOTICE_VERSION}.html` (R13).

### Implementation for User Story 6

- [X] T065 [US6] Implementar `GET /aviso` y `POST /aviso` en `src/garmin_hub/web/routes/garmin_accounts.py`, con la validación de `next` de T062 y `notice.accept`.
- [X] T066 [P] [US6] Redactar `src/garmin_hub/web/templates/garmin/notice_v1.html` en español con el contenido de FR-011 y US6-4:
  - qué datos se descargan: actividades, recorridos con GPS y datos de salud (pulsaciones, sueño y HRV);
  - quién puede verlos y que el administrador nunca puede;
  - que la cuenta debe ser propia;
  - que se puede desvincular y borrar en cualquier momento;
  - que la contraseña de Garmin no se guarda.
  - Además, crear `src/garmin_hub/web/templates/garmin/notice.html`, con la casilla "He leído y acepto" y el `next` oculto, que incluye la plantilla de la versión vigente.
- [X] T067 [US6] Añadir la puerta del aviso a `GET /{account_id}/reautenticar` y `POST /{account_id}/reautenticar` en `src/garmin_hub/web/routes/garmin_accounts.py`: `303 → /cuentas-garmin/aviso?next=/cuentas-garmin/<id>/reautenticar`.
- [X] T068 [US6] Añadir el aviso (2) de contracts/http.md a `home` en `src/garmin_hub/web/routes/account.py` y a `src/garmin_hub/web/templates/home.html`: solo si hay al menos una cuenta en `valid`, `reauth_required` o `error` y `has_accepted_current` es falso.

**Checkpoint**: T062–T064 en verde; paso 2 de quickstart. Con esto el MVP es usable por usuarios reales.

---

## Phase 9: User Story 7 - Comprobar que una cuenta sigue funcionando (Priority: P3)

**Goal**: "Comprobar" verifica el acceso con Garmin sin descargar datos, como mucho una vez por minuto, y actualiza el estado si el acceso ya no vale.

**Independent Test**: comprobar una cuenta con `profile_id=1` (válida) y otra con `9001` (rechazada), y ver la fila actualizada por HTMX y los estados resultantes.

### Tests for User Story 7 ⚠️

- [X] T069 [P] [US7] Test de integración en `tests/integration/test_garmin_check_http.py`:
  - **Acceso válido**: fragmento con "Funciona correctamente", `last_checked_at = now` y `garmin.account_checked` con `result: ok` (US7-1).
  - **Acceso rechazado** (`profile_id=9001`): pasa a `reauth_required`, con su mensaje, `garmin.status_changed` (`from valid`, `to reauth_required`, `via check`) y `result: token_rejected` (US7-2, FR-016).
  - **Errores transitorios**: con `script_verify` → `RateLimited` y `GarminUnavailable`, el mensaje de R10, el estado sin cambiar y `last_checked_at` sin cambiar (US7-3, FR-017, R6).
  - **Carrera**: un `verify` del cliente falso que desvincula la cuenta antes de devolver unos accesos renovados. La cuenta queda `unlinked`, sin `garmin_token`, y se muestra "La cuenta ha cambiado mientras se comprobaba; recarga la página." (FR-021).
  - **Una comprobación por minuto**: la segunda comprobación en menos de 60 s da 409 "Ya se ha comprobado hace menos de un minuto." sin ninguna llamada nueva a `fake.calls`. A los 61 s se permite (US7-4, FR-025).
  - **Candado**: con el candado ocupado → 409. Después de comprobar, `request_lease_until` queda NULL.
  - **Accesos renovados**: se guarda el token nuevo, con `updated_at` y la versión vigente.
  - **Errores de la cuenta**: un token con una `key_version` no configurada pasa a `error` con `token_undecryptable`, `via token_use`, sin llamar a Garmin. Una identidad distinta pasa a `error` con `identity_mismatch`.
  - **Estados sin comprobación**: `unlinked` y `deleting` → 409.
  - **Otras cuentas**: con otra cuenta del mismo usuario, esa no cambia (SC-003).

### Implementation for User Story 7

- [X] T070 [US7] Implementar `check_account(...)` en `src/garmin_hub/garmin_accounts/accounts.py` (R6, R10, R12):
  1. `get_own_account`, un estado permitido, `claim_check` y `acquire`, en una transacción corta;
  2. `load_tokens`; si lanza `UndecryptableToken`, la cuenta pasa a `error`;
  3. `client.verify` fuera de la transacción;
  4. una transacción corta que aplica el resultado con `update_if_active`: estado y `last_checked_at`, este último solo si el resultado es definitivo según R6; el token renovado solo si la actualización ha afectado a una fila; y la auditoría;
  5. `release` en un `finally`.
- [X] T071 [US7] Implementar `POST /{account_id}/comprobar` en `src/garmin_hub/web/routes/garmin_accounts.py`. Devuelve el fragmento `garmin/_row.html` con el mensaje del resultado; los errores 409 van en el mismo fragmento, según la `responseHandling` de htmx de 001. Añadir el botón `hx-post` en `_row.html`.

**Checkpoint**: T069 en verde; pasos 9 y 16 de quickstart.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: exportación, rotación de claves, verificación de que no hay secretos, prueba con Garmin real, documentación y validación final.

- [X] T072 [P] Test de integración en `tests/integration/test_garmin_export.py`:
  - `GET /cuenta/exportar` incluye `garmin_accounts` (con `garmin_account_id`, `alias`, `status`, `linked_at`, `last_login_at`, `last_sync_at`, `last_checked_at` y `unlinked_at`) y `data_notice_acceptances` (con `notice_version` y `accepted_at`);
  - no contiene `ciphertext`, `key_version`, `garmin_profile_id`, ningún correo de Garmin ni cuentas de otros usuarios (FR-030).
- [X] T073 Implementar `src/garmin_hub/garmin_accounts/export.py` con `register_export_section("garmin_accounts", ...)` y `register_export_section("data_notice_acceptances", ...)`, e importarlo desde `create_app` (data-model.md, "Registros ampliables").
- [X] T074 [P] Test de integración en `tests/integration/test_cli_key_reencrypt.py`:
  - con tokens cifrados con la versión 1 y `GARMIN_HUB_MASTER_KEYS=2:<k2>,1:<k1>`, `key reencrypt` deja todas las filas con `key_version=2`, descifrables, y escribe `Accesos recifrados: <n>. Pendientes con versiones no configuradas: 0.`, con salida 0;
  - repetirlo da `Accesos recifrados: 0.`;
  - una fila con la versión 3 no configurada se cuenta como pendiente y la salida es 1;
  - la salida no contiene ningún token ni clave.
- [X] T075 Implementar `key reencrypt` en `src/garmin_hub/cli/main.py` según contracts/cli.md: una transacción por fila, con los códigos de salida 0, 1, 2 y 3.
- [X] T076 [P] Test de integración SC-002 en `tests/integration/test_garmin_no_plaintext.py`:
  - **Recorrido**: con un correo, una contraseña, un código MFA, unos accesos y un `profile_id` centinela (por ejemplo 987654321) (un `FakeGarminClient` configurado para devolver `GarminTokens` con un centinela), vincula con y sin MFA, reautentica, comprueba y desvincula conservando y borrando.
  - **Base de datos**: recorre todas las columnas de texto y binarias de todas las tablas del schema y comprueba que no aparece ningún centinela en claro. El `profile_id` solo puede estar en `garmin_account.garmin_profile_id`, y nunca en `audit_event.details` (FR-028a).
  - **Logs**: comprueba lo mismo en los logs capturados con `JsonFormatter`.
  - **Respuestas**: comprueba lo mismo en los cuerpos de todas las respuestas.
- [X] T077 [P] Ampliar `tests/integration/test_spanish_messages.py` con los mensajes de research R10, R6, R7 y R9 y con las etiquetas de estado de contracts/http.md, que deben estar en español y sin texto técnico de la librería.
- [X] T078 [P] Crear `tests/live/test_garminconnect_client.py` (marca `live`, research R16):
  - se omite si faltan `GARMIN_HUB_LIVE_GARMIN_EMAIL` o `GARMIN_HUB_LIVE_GARMIN_PASSWORD`;
  - hace `start_login`, y `complete_mfa` con `input()` si se pide;
  - comprueba `profile_id > 0` y que `tokens.value` es un JSON con `di_refresh_token`;
  - hace `verify`;
  - con `caplog` a nivel `DEBUG`, comprueba que ni el correo ni la contraseña aparecen en los registros;
  - mide la duración de `start_login` y avisa si supera 45 s (SC-001, R11);
  - nunca imprime ni guarda los tokens.
- [X] T079 [P] Actualizar `README.md`, en español:
  - la vinculación de cuentas Garmin;
  - el secreto `GARMIN_HUB_MASTER_KEYS` y la rotación (`key generate`, `key reencrypt`);
  - el cliente falso para desarrollo;
  - `pytest -m live`;
  - la limitación de un solo proceso web por el MFA (R3).
- [X] T080 [P] Actualizar `specs/002-garmin-account-linking/quickstart.md` con los comandos, las salidas y los mensajes reales tras la implementación, y corregir cualquier diferencia con `contracts/`.
- [ ] T081 Validación final:
  - **Automática**: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` y `uv run pytest -m integration`, todos en verde.
  - **Migraciones**: `garmin-hub db upgrade`, la bajada a `0001_user_access` y una nueva subida sobre una base desechable.
  - **Manual**: recorrer los pasos 0–17 de `quickstart.md` con el cliente falso en Windows (PowerShell) y en Linux/WSL (bash).
  - **Garmin real** (opcional): `pytest -m live` con una cuenta Garmin propia.
  - **Registro**: anotar el resultado y el tiempo medido de SC-001 (< 1 min) en `specs/002-garmin-account-linking/checklists/requirements.md`, en la sección "Notes".

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (fase 1)**: sin dependencias. T002 y T003 en paralelo tras T001.
- **Foundational (fase 2)**: depende de Setup y **bloquea** todas las historias. Dentro de la fase:
  - T016 → T017;
  - T020 → T021, T022, T023 y T024 (T023 depende también de T021);
  - T025 → T026;
  - T028 depende de T016, T020, T025 y T027;
  - T029 depende de T017, T018, T022, T023, T024 y T028;
  - T031 depende de T029.
- **Historias (fases 3–9)**: dependen solo de la fase 2.
- **Polish (fase 10)**: depende de todas las historias (T076 recorre el ciclo completo).

### User Story Dependencies

- **US1 (P1)**: tras la fase 2. Sus tests usan `accept_notice`, no la página de US6.
- **US2 (P1)**: tras la fase 2. Usa `make_garmin_account`, no US1.
- **US3 (P1)**: tras la fase 2. La matriz recorre las rutas existentes en cada momento; se vuelve a ejecutar tras cada historia posterior.
- **US4 (P2)**: tras la fase 2. Amplía `POST /mfa`, creado en US1 (T039).
- **US5 (P2)**: tras la fase 2. T059 completa el gancho de recuperación de T038 (US1).
- **US6 (P2)**: tras la fase 2. T067 añade la puerta a las rutas de US4 (T052).
- **US7 (P3)**: tras la fase 2. Usa `_row.html` (T046, US2).

### Within Each User Story

- Los tests primero, y deben fallar.
- Después el dominio en `garmin_accounts/`, luego las rutas y por último las plantillas.
- En cada checkpoint, ruff limpio y tests de la historia en verde.

### Parallel Opportunities

- **Fase 2**: los tests T004–T015 en paralelo. T018, T019 y T027 en paralelo con T016. T021, T022 y T024 en paralelo tras T020.
- **Historias**: los tests marcados [P] de cada historia en paralelo. Las plantillas ([P]) en paralelo con el servicio.
- **Con más de una persona**: US2 y US7 tocan ficheros casi disjuntos de US4 y US5.

---

## Parallel Example: User Story 1

```bash
# Tests de US1 en paralelo (escribir primero, deben fallar):
Task: "Test de integración de la vinculación en tests/integration/test_garmin_link_http.py"
Task: "Test de integración del MFA en tests/integration/test_garmin_link_mfa.py"
Task: "Test de integración del límite de intentos en tests/integration/test_garmin_link_ratelimit.py"
Task: "Test de integración de la auditoría en tests/integration/test_garmin_link_audit.py"

# Plantillas en paralelo con el servicio:
Task: "Crear las plantillas garmin/link.html y garmin/mfa.html"
Task: "Implementar start_link en src/garmin_hub/garmin_accounts/accounts.py"
```

## Parallel Example: Foundational

```bash
Task: "Test unitario de TokenCipher en tests/unit/test_token_cipher.py"
Task: "Test unitario de FakeGarminClient en tests/unit/test_fake_garmin_client.py"
Task: "Test unitario del mapeo de excepciones en tests/unit/test_garminconnect_mapping.py"
Task: "Test de integración de la migración en tests/integration/test_migration_0002.py"
```

---

## Implementation Strategy

### MVP First (P1 + aviso)

1. Fase 1 y fase 2, con su checkpoint.
2. US1 → US2 → US3, con un checkpoint tras cada una.
3. US6, porque sin la página del aviso un usuario real no puede vincular (SC-006).
4. **STOP and VALIDATE**: pasos 0–8 y 10–11 de quickstart.

### Incremental Delivery

1. MVP.
2. US4 → US5, las P2 restantes.
3. US7, la P3.
4. Fase 10 y validación final (T081).

---

## Notes

- [P] = ficheros distintos y sin dependencias pendientes.
- El único cambio de esquema es `0002_garmin_accounts`, con su test de subida y bajada (T014). Cualquier otro cambio requiere una migración nueva.
- Commit al cerrar cada tarea o grupo lógico, con mensajes en inglés.
- No se añade nada fuera de spec.md ni de plan.md. Lo de features posteriores (descarga de datos, `sync_job`, `RawStore`, `can_view`, `GARMIN_HUB_RAW_DIR`) no se implementa aquí. Plan.md, en "Notas para features posteriores", lista lo que esas features deben respetar.
