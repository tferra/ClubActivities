# Research: Gestión de usuarios y acceso (001)

Decisiones técnicas de la feature 001. El contexto técnico general del proyecto (stack, interfaces,
cola de trabajos, etc.) ya lo fijó el propietario y no se reabre aquí. Al final se listan las
investigaciones transversales que se aplazan a la feature que las necesita.

---

## R1. Acceso a SQL Server: síncrono o asíncrono

- **Decision**: usar SQLAlchemy Core 2.x en modo **síncrono**, con `pyodbc` (ODBC Driver 18).
  Las rutas de FastAPI se declaran con `def` (no `async def`), de modo que se ejecutan en el
  pool de hilos de Starlette. El engine es único por proceso, con `pool_pre_ping=True`.
  **Excepción**: las rutas que aplican el límite de intentos (`POST /login`, `POST /alta/codigo`,
  `POST /alta` y `POST /restablecer`) son `async def`, ejecutan el acceso a la base de datos con
  `run_in_threadpool` y esperan el retardo de R10 con `await anyio.sleep`, para que un retardo no
  ocupe un hilo del pool (ver R10).
- **Rationale**: `pyodbc` es síncrono. Las alternativas asíncronas (`aioodbc`) añaden una
  dependencia poco madura sin aportar nada a esta escala (decenas de usuarios). El pool de hilos
  basta.
- **Alternatives considered**: `aioodbc` + `async def`, descartado por madurez y complejidad.
  ORM declarativo, descartado porque Core es suficiente y lo fija el contexto técnico.

## R2. Esquema, nombres y aislamiento de los tests

- **Decision**:
  - Todo el esquema se crea en un schema configurable `GARMIN_HUB_DB_SCHEMA`, `gh` por defecto.
  - Tablas y columnas en inglés (constitución XII): `app_user`, `invitation`,
    `password_reset_code`, `user_session`, `login_attempt`, `audit_event`. No se usa `user`
    porque es palabra reservada en SQL Server.
  - Los tests de integración crean un schema aleatorio (`gh_t_<hex>`) en la base de
    `GARMIN_HUB_TEST_DB_URL`, aplican las migraciones y lo eliminan al terminar.
- **Rationale**: el schema por ejecución evita necesitar el permiso `CREATE DATABASE` en la base
  que aporta el propietario y permite ejecuciones en paralelo.
- **Alternatives considered**: una base de datos por ejecución (requiere más permisos); SQLite
  para los tests (no soporta índices filtrados ni triggers equivalentes, lo que daría falsos
  positivos).

## R3. Identificadores y tiempos

- **Decision**:
  - `user_id`, `invitation_id` y `reset_id` son `UNIQUEIDENTIFIER` generados en la aplicación
    (`uuid4`).
  - `audit_event` y `login_attempt` usan `BIGINT IDENTITY`.
  - Las marcas de tiempo son `DATETIME2(3)` en UTC, escritas siempre desde la aplicación con
    `datetime.now(UTC)`.
  - La lógica que depende de la hora recibe un `now: Callable[[], datetime]` inyectable, para
    poder probarla sin dormir.
- **Rationale**: los identificadores son estables (constitución XI). En tablas de pocas filas la
  fragmentación de un UUID aleatorio es irrelevante.
- **Alternatives considered**: `NEWSEQUENTIALID()` (ata la generación a la base de datos); UUIDv7
  (Python 3.12 no lo trae en la librería estándar).

## R4. Hash de contraseñas

- **Decision**:
  - `argon2-cffi` con `PasswordHasher()` y sus parámetros por defecto (perfil RFC 9106 de bajo
    consumo de memoria).
  - `check_needs_rehash` tras cada inicio de sesión correcto.
  - Las contraseñas se normalizan con NFKC antes de calcular el hash.
  - Para igualar los tiempos (SC-005), cuando el correo no existe se verifica igualmente contra un
    hash señuelo precalculado.
- **Rationale**: lo exige la constitución (IV). Los parámetros por defecto se mantienen al día con
  la librería.
- **Alternatives considered**: bcrypt y scrypt (no los permite la constitución).

## R5. Política de contraseñas y lista de contraseñas comunes

- **Decision**:
  - Longitud entre 12 y 128 caracteres tras la normalización NFKC.
  - Se rechaza una contraseña si:
    - (a) está, en minúsculas, en la lista de contraseñas comunes;
    - (b) contiene, sin distinguir mayúsculas, la parte local completa del correo (si tiene 4 o
      más caracteres) o alguna palabra completa del nombre de 4 o más caracteres (las palabras se
      separan por espacios, guiones o apóstrofos) (FR-016);
    - (c) es un único carácter repetido.
  - La lista se vendoriza como `security/data/common_passwords.txt.gz`. Sale de la lista
    "top 1M" de SecLists (licencia MIT), **filtrada a las entradas de 12 o más caracteres**, que
    son las únicas relevantes con el mínimo de 12; queda en unos pocos cientos de KB. Se carga
    perezosamente en un `frozenset`.
- **Rationale**: se ajusta a NIST SP 800-63B (lista de contraseñas comprometidas y sin reglas de
  composición) sin depender de la red (constitución IX) ni de librerías pesadas.
- **Alternatives considered**: `zxcvbn` (dependencia extra y mensajes en inglés); consultar Have
  I Been Pwned (red externa en el camino crítico).

## R6. Códigos de invitación y de restablecimiento

- **Decision**:
  - Son 20 caracteres en base32 de Crockford (100 bits de entropía) generados con `secrets`, y se
    muestran en grupos `XXXX-XXXX-XXXX-XXXX-XXXX`.
  - Al introducirlos se normalizan: mayúsculas, sin guiones ni espacios, O→0, I/L→1.
  - Se almacena `HMAC-SHA256(k_code, código_normalizado)` en `BINARY(32)`, con índice único.
- **Rationale**: con 100 bits no hace falta un hash lento; el HMAC con una clave del servidor
  impide comprobar códigos aunque se filtre la base de datos. El formato es fácil de dictar o
  copiar.
- **Alternatives considered**: `token_urlsafe` (difícil de dictar); argon2 sobre el código
  (innecesario e impide buscar por hash).

## R7. Derivación de claves desde `GARMIN_HUB_SESSION_SECRET`

- **Decision**:
  - Un único secreto obligatorio de 32 bytes o más (`GARMIN_HUB_SESSION_SECRET`).
  - De él se derivan subclaves con `HMAC-SHA256(secret, etiqueta)`:
    - `session-id`: hash del identificador de sesión;
    - `csrf`: token CSRF ligado a la sesión;
    - `code`: códigos de invitación y restablecimiento;
    - `email-rl`: seudónimo del correo en `login_attempt`;
    - `ip-rl`: seudónimo de la dirección de red en `login_attempt`;
    - `anon-csrf`: token CSRF de los formularios públicos.
  - Rotar el secreto invalida las sesiones y los códigos pendientes; está documentado en
    quickstart.
- **Rationale**: un solo secreto que gestionar, con separación de dominios entre usos.
- **Alternatives considered**: un secreto por uso (más variables sin beneficio a esta escala).

## R8. Sesiones en servidor

- **Decision**:
  - El identificador de sesión es `secrets.token_urlsafe(32)` y va en la cookie.
  - En `user_session` se guarda solo `HMAC(k_session, id)`.
  - Cookie `__Host-gh_session` con `HttpOnly`, `Secure`, `SameSite=Lax` y `Path=/`, **siempre**,
    también en desarrollo (constitución IV, sin excepciones). Chrome, Edge y Firefox tratan
    `http://localhost` como contexto seguro y aceptan ahí cookies `Secure` y `__Host-`; el
    quickstart pide usar uno de ellos y `GARMIN_HUB_PUBLIC_URL=http://localhost:8000`.
  - Los tests usan `TestClient(app, base_url="https://testserver")`, porque `httpx` no envía
    cookies `Secure` sobre http.
  - Cada petición resuelve la sesión con un JOIN a `app_user` con `status='active'`. Si el usuario
    no está activo o la sesión ha caducado (por inactividad o por superar la duración máxima), la
    sesión se borra y se redirige a `/login`. Así, la desactivación tiene efecto inmediato
    (FR-026).
  - `last_seen_at` se actualiza como mucho una vez cada 60 s, para reducir escrituras.
  - Al iniciar sesión siempre se crea una sesión nueva (FR-021).
  - Las sesiones caducadas se purgan de forma oportunista al iniciar sesión (lotes de `TOP 500`).
- **Rationale**: lo exige la constitución (sesión en servidor, cookie segura). La revocación es
  inmediata y no hace falta un almacén extra (constitución X).
- **Alternatives considered**: sesiones firmadas en la cookie (no permiten revocarlas al
  desactivar a un usuario).

## R9. CSRF

- **Decision**:
  - **Con sesión**: token = `HMAC(k_csrf, session_id)`. Va como campo oculto `csrf_token` en
    los formularios y como cabecera `X-CSRF-Token` en HTMX, mediante `hx-headers` en `<body>`. Una
    **dependencia de FastAPI** (`require_csrf`), aplicada a nivel de router a toda ruta POST, PUT,
    PATCH y DELETE, lo exige comparando en tiempo constante. Se descarta un middleware
    `BaseHTTPMiddleware`, porque leer el formulario en él puede dejar el cuerpo vacío para la
    ruta; con la dependencia, `request.form()` queda en caché en el mismo `Request` y la ruta
    recibe los campos.
  - **Sin sesión** (login, alta, restablecimiento): doble envío firmado. La cookie
    `__Host-gh_csrf` contiene un nonce aleatorio y el formulario lleva `HMAC(k_anon_csrf, nonce)`.
  - **Defensa adicional**: si llega la cabecera `Origin`, debe coincidir con
    `GARMIN_HUB_PUBLIC_URL`.
- **Rationale**: no necesita columnas extra y protege también el login contra la fijación de
  sesión.
- **Alternatives considered**: librerías como `starlette-csrf` o `fastapi-csrf-protect`. Son una
  dependencia extra para unas 40 líneas de código, y no resuelven bien a la vez HTMX y los
  formularios anónimos.

## R10. Límite de intentos

- **Decision**: la tabla `login_attempt` guarda
  `(attempted_at, email_hmac, ip_hmac, kind, succeeded)` y aplica estas reglas antes de verificar
  la credencial:
  1. **Por correo y origen**: si hay 5 o más fallos de tipo `login` o `current_password` para el
     par `(email_hmac, ip_hmac)` en los últimos 15 minutos, posteriores al último inicio de sesión
     correcto de ese par, se bloquea (FR-030). Un acierto reinicia el recuento.
  2. **Por origen**: si hay 20 o más fallos de tipo `login` o `code_redeem` desde el mismo
     `ip_hmac` en 15 minutos, se bloquea (FR-031). `current_password` no cuenta aquí.
  3. **Global por correo**: con n fallos de tipo `login` para el mismo `email_hmac` en 60
     minutos, si n es 50 o más se aplica un retardo de `min(10 s, 0.5 s × (n − 49))` antes de
     responder, sin bloquear (FR-030a). Al cruzar el umbral se registra un evento de auditoría.
  4. Incluso cuando la petición está bloqueada se ejecuta una verificación de argon2, para no
     abrir un canal de tiempos.
  - `check_attempts` **devuelve** la decisión y el retardo; no duerme. La ruta `async def` espera
    el retardo con `await sleep(delay)` (inyectable; `anyio.sleep` en producción) **fuera** de
    la transacción y del pool de hilos. Así, muchos correos atacados a la vez no agotan los
    hilos del servidor ni retienen conexiones.
  - Las filas de más de 24 horas se purgan de forma oportunista.
  - Ni el correo ni la dirección de red se guardan en claro en esta tabla: ambos van como HMAC
    (`email-rl` e `ip-rl`), que basta para contar por igualdad.
- **Rationale**: una sola tabla y consultas sobre índices `(email_hmac, attempted_at)` e
  `(ip_hmac, attempted_at)`. Nadie puede bloquear al usuario legítimo desde otro origen. Un
  `time.sleep` dentro de una ruta síncrona permitiría agotar el pool de hilos (40 por defecto).
- **Alternatives considered**: contadores en memoria (no sobreviven a varios procesos ni a
  reinicios, y Redis está prohibido); `slowapi` (limita por ruta, no por par correo + origen).

## R11. Origen del cliente detrás de Caddy

- **Decision**: uvicorn se lanza con `proxy_headers=True` y
  `forwarded_allow_ips=GARMIN_HUB_TRUSTED_PROXIES`. Por defecto vale `127.0.0.1`; en Compose,
  la red interna. El origen es `request.client.host` tras ese procesamiento.
- **Tratamiento como dato personal**: la dirección completa solo vive en memoria durante la
  petición. El módulo `security/ip.py` ofrece:
  - `client_ip(request) -> str`;
  - `ip_prefix(ip) -> str`, que reduce a la red (IPv4 /24 → `203.0.113.0/24`, IPv6 /48 →
    `2001:db8:1::/48`); se usa en `audit_event.ip_prefix` y en los logs;
  - `ip_hmac(keys, ip) -> bytes`, con la subclave `ip-rl`; se usa solo en `login_attempt`.
  Una dirección no válida se trata como `unknown`.
- **Rationale**: así no se puede falsificar `X-Forwarded-For` desde internet.
- **Alternatives considered**: leer `X-Forwarded-For` a mano (propenso a errores).

## R12. Cabeceras de seguridad y HTMX con CSP estricta

- **Decision**:
  - Un middleware propio añade estas cabeceras:
    - CSP:
      ```
      default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
      object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'
      ```
    - `X-Content-Type-Options: nosniff`
    - `Referrer-Policy: same-origin`
    - `Permissions-Policy: geolocation=(), camera=(), microphone=()`
    - `Cache-Control: no-store` en las respuestas autenticadas
    - HSTS (`max-age=31536000`) cuando la URL pública es https
  - HTMX 2.x se vendoriza en `static/vendor/` y se desactivan sus estilos inline con
    `<meta name="htmx-config" content='{"includeIndicatorStyles":false}'>`.
  - No hay scripts inline.
- **Rationale**: la CSP sin `unsafe-inline` es viable porque HTMX funciona con atributos.
- **Alternatives considered**: delegar todas las cabeceras en Caddy. Se descarta para el
  desarrollo sin contenedores y para los tests; Caddy puede repetirlas.

## R13. Configuración y secretos obligatorios (FR-001)

- **Decision**:
  - `load_env_file(path=Path(".env")) -> Mapping[str, str]` lee `.env` con
    `dotenv.dotenv_values` **solo si** el fichero existe y `GARMIN_HUB_ENV` vale `dev`, tomado
    del entorno real o, si no está ahí, del propio `.env`. En cualquier otro caso devuelve un
    mapa vacío. Las variables del entorno real siempre tienen prioridad.
  - `Settings` (pydantic-settings, prefijo `GARMIN_HUB_`) recoge los valores no secretos y los
    tiempos configurables de FR-002, recibiendo ese mapa como valores de respaldo.
    `GARMIN_HUB_PUBLIC_URL` es **obligatoria** (CSRF, HSTS y cookies dependen de ella): si falta
    o no es una URL http(s) válida, se lanza `MissingConfigError` y el CLI sale con el código 2
    y el mensaje `Error: falta configuración obligatoria: GARMIN_HUB_PUBLIC_URL.`
  - `SecretProvider` (protocolo con `get(name) -> str | None`) tiene la implementación
    `EnvSecretProvider(fallback=load_env_file())`, que consulta `os.environ` y, si no está ahí,
    el mapa de `.env`. Así los secretos de `.env` llegan al proveedor en desarrollo.
  - `load_secrets(provider)` comprueba los secretos obligatorios de 001:
    - `GARMIN_HUB_DB_URL`;
    - `GARMIN_HUB_SESSION_SECRET` (de 32 bytes o más).
  - Si alguno falta, lanza `MissingSecretsError` con la lista de **nombres**. El CLI y el arranque
    web la convierten en un mensaje en español y en el código de salida 2.
  - `GARMIN_HUB_MASTER_KEYS` y `GARMIN_HUB_RAW_DIR` se añaden a la lista de obligatorios en la
    feature que introduce los tokens de Garmin y los ficheros crudos (constitución X: no se pide
    lo que no se usa).
- **Rationale**: es la única puerta de entrada de los secretos (constitución IV y VII) y se podrá
  sustituir por Key Vault.
- **Alternatives considered**: leer los secretos como campos de `Settings` (mezcla secretos y
  configuración e impide cambiar el proveedor).

## R14. Logging sin secretos

- **Decision**:
  - Se usa `logging` de la librería estándar con un formateador JSON propio (una línea por
    evento) y `RotatingFileHandler` en `GARMIN_HUB_LOG_DIR` (10 MB × 5), además de stderr.
  - Un filtro `RedactingFilter`:
    - (a) sustituye por `***` el valor de las claves sensibles en `extra` y en `args` (`password`,
      `pass`, `secret`, `token`, `code`, `cookie`, `authorization`, `session`, `csrf`, `email`,
      `ip`, `client`, `remote_addr`, `db_url`);
    - (b) enmascara con expresiones regulares, en el mensaje, los correos, los códigos con
      formato `XXXX-XXXX-…`, las direcciones IPv4 e IPv6 completas y la contraseña de una URL de
      conexión (`//usuario:***@`).
  - El log de acceso de uvicorn se **desactiva** (`access_log=False`). Lo sustituye
    `AccessLogMiddleware` (ASGI puro, en `logging_setup.py`), que registra método, ruta **sin**
    query string, estado, duración e `ip_prefix` (R11), nunca la dirección completa.
  - Los logs de error de uvicorn pasan por el mismo filtro.
- **Rationale**: lo exigen la constitución (IV: ningún dato personal en logs; la dirección de red
  lo es según el RGPD) y SC-004. El test de "ciclo completo" captura todos los logs y busca los
  valores en claro.
- **Alternatives considered**: `structlog` o `python-json-logger`. No hacen falta para un
  formateador de unas 30 líneas.

## R15. Registro de auditoría de solo inserción

- **Decision**:
  - La tabla `audit_event` tiene un trigger `INSTEAD OF UPDATE, DELETE` que hace `THROW`.
  - La migración, además, aplica `DENY UPDATE, DELETE` si existe un rol `gh_app` (es opcional y
    está documentado).
  - Columnas `actor_user_id` y `subject_user_id` sin FK, para que el borrado del usuario no las
    arrastre (FR-035).
  - `details` es JSON con claves en lista blanca, nunca correos ni nombres.
  - El origen se guarda como `ip_prefix` (red reducida, R11), nunca la dirección completa, porque
    la tabla no puede limpiarse tras borrar al usuario.
- **Rationale**: el trigger garantiza la regla aunque la cuenta de conexión del propietario sea
  `db_owner`.
- **Alternatives considered**: tablas temporales o ledger de SQL Server (requieren versión o
  edición concreta y son excesivas aquí).

## R16. Borrado de usuario con hook ampliable

- **Decision**:
  - El módulo `accounts/deletion.py` mantiene un registro ordenado de pasos:
    `register_deletion_step(name, order, fn)`, donde
    `fn(ctx: DeletionContext, user_id: UUID) -> None`.
  - Los pasos deben ser idempotentes.
  - Flujo:
    1. En una transacción: `status='pending_deletion'`, borrado de las sesiones y auditoría
       `user.deletion_requested`.
    2. Se ejecutan los pasos registrados.
    3. Se hace `DELETE app_user` y se registra la auditoría `user.deleted`.
  - Si algo falla, el usuario queda en `pending_deletion`: no puede entrar y en el login se trata
    como inexistente. El listado de administración muestra "Borrado pendiente" con la acción
    "Reintentar".
  - Al pasar a `pending_deletion`, en la misma transacción, los códigos de restablecimiento
    pendientes pasan a `expired` (igual que al desactivar, FR-029).
  - Pasos propios de 001:
    - borrar `password_reset_code`;
    - poner a NULL las referencias de `invitation` (`created_by`, `used_by`, `revoked_by`).
  - Las features posteriores registran los suyos: cuentas Garmin, tokens, ficheros crudos (con
    `RawStore` en el contexto), consentimientos y membresías.
- **Rationale**: cumple FR-028 y FR-028a y el caso límite de "borrado que falla a mitad", y ofrece
  un único punto de extensión explícito.
- **Alternatives considered**: `ON DELETE CASCADE` en todas las FK. SQL Server rechaza varias
  rutas de cascada hacia `app_user`, y la cascada no cubre los ficheros crudos.

## R17. Invitaciones: unicidad y consumo atómico

- **Decision**:
  - Índice único filtrado `UX_invitation_pending_email` sobre `(email) WHERE status='pending'`.
  - Antes de crear una invitación, en la misma transacción, las pendientes caducadas de ese correo
    pasan a `status='expired'`.
  - El consumo es una sentencia
    `UPDATE … SET status='used' … WHERE code_hash=? AND status='pending' AND expires_at>?`;
    solo si `rowcount == 1` se inserta el usuario, en la misma transacción.
  - Los códigos de restablecimiento siguen la misma pauta, con el índice único filtrado por
    `user_id WHERE status='pending'` y el paso de los anteriores a `superseded`.
  - El canje de un código de restablecimiento exige además `app_user.status='active'` en la
    misma sentencia (JOIN), y al desactivar a un usuario sus códigos pendientes pasan a
    `expired` (FR-029).
  - Si al canjear una invitación el `INSERT` de `app_user` viola `UX_app_user_email` (el correo
    se registró por otra vía), la transacción se revierte y se responde con el mensaje genérico
    de código, sin consumirlo. `admin create` rechaza un correo con una invitación pendiente.
- **Rationale**: la base de datos garantiza FR-005a, FR-009 y SC-002, incluso con concurrencia.
- **Alternatives considered**: bloqueos en la aplicación (no sirven con varios procesos).

## R18. Último administrador

- **Decision**: se cuentan los administradores activos con `WITH (UPDLOCK, HOLDLOCK)` dentro de la
  transacción que desactiva o borra a un administrador. Se rechaza la operación si el resultado
  dejaría 0. Que un administrador se desactive a sí mismo se rechaza siempre.
- **Rationale**: evita la carrera de dos administradores desactivándose mutuamente (FR-027).

## R19. Dependencias

| Paquete | Uso | Justificación |
|---------|-----|---------------|
| fastapi, uvicorn | web | Fijados por el contexto técnico |
| jinja2 | plantillas | Fijado por el contexto técnico |
| python-multipart | formularios | Lo exige FastAPI para `Form` |
| sqlalchemy, pyodbc, alembic | base de datos | Fijados por el contexto técnico |
| pydantic-settings | configuración | Fijado por el contexto técnico |
| argon2-cffi | contraseñas | Constitución IV |
| typer | CLI | Fijado por el contexto técnico |
| python-dotenv | lectura de `.env` en desarrollo (R13) | Ya llega como dependencia de pydantic-settings; se declara porque se usa directamente |
| anyio | `anyio.sleep` del retardo de R10 | Ya llega con Starlette; se declara porque se usa directamente |
| hatchling | backend de build (`[build-system]`) | Solo en tiempo de build; es el backend por defecto de `uv init --package` |
| *(dev)* pytest, ruff, httpx | calidad | Constitución IX; `httpx` lo necesita el `TestClient` |

Las versiones exactas se fijan en `pyproject.toml` y en `uv.lock` durante la implementación.
`cryptography`, `garminconnect`, `apscheduler`, `tenacity`, `numpy` y la librería de FIT entran
con las features que las usan.

---

## Investigaciones transversales aplazadas

Están en el contexto técnico del proyecto, pero no las necesita 001. Se investigarán en el
`research.md` de la feature que las introduce:

| Tema | Feature que lo resolverá |
|------|--------------------------|
| Autenticación y MFA de la versión vigente de `garminconnect` (¿sigue usando `garth`?) y estado intermedio cifrado con TTL | Vinculación de cuentas Garmin |
| `MultiFernet` con `key_version` y comando `key generate` | Vinculación de cuentas Garmin |
| `fitdecode` frente a `fitparse` (semicírculos y dinámicas de carrera) | Descarga e ingesta de actividades |
| Columnstore frente a fila comprimida para `activity_record` y prueba con 100 actividades de 5 h | Descarga e ingesta de actividades |
| `UPDLOCK, READPAST`, latido y scheduler de `sync_job` | Cola de sincronización y worker |
| LTTB, Plotly `scattergl` y Leaflet vendorizados | Visualización de actividades |
| Uso de las categorías de `can_view` (`activities`, `route`, `health`, constitución v1.0.1) | Clubes, entrenadores y consentimiento |
