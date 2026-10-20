# Research: Vinculación y gestión de cuentas Garmin (002)

Decisiones técnicas de la feature 002. Se apoya en las decisiones de la feature 001
(`specs/001-user-access/research.md`, R1–R19), que no se reabren: SQLAlchemy Core síncrono,
schema configurable, UUID y `DATETIME2(3)` en UTC, sesiones en servidor, CSRF por router,
auditoría de solo inserción, borrado y exportación con registros ampliables.

---

## R1. Librería de acceso a Garmin

- **Decision**: usar `garminconnect==0.3.17` (publicada el 2026-09-29), fijada a la versión exacta.
  - Se usa directamente su clase de bajo nivel `garminconnect.client.Client`, no el envoltorio
    `garminconnect.Garmin`, porque el envoltorio guarda el correo y la contraseña en
    `self.username` y `self.password` durante toda su vida, también mientras espera el MFA.
    `Client.login(email, password, return_on_mfa=True)` solo usa la contraseña dentro de la
    llamada.
  - La librería solo se importa en `src/garmin_hub/garmin/garminconnect_client.py`
    (constitución III). Un test recorre los módulos y falla si `garminconnect` o `curl_cffi` se
    importan en otro sitio.
  - Las actualizaciones de versión se hacen a propósito, pasando antes el test `live` (R16).
- **Rationale**:
  - `garth` (la base anterior de `garminconnect`) se declaró obsoleta en marzo de 2026, porque
    Garmin cambió su flujo de autenticación y los logins nuevos dejaron de funcionar.
  - `garminconnect` 0.3.x reescribió el login con varias estrategias (móvil, widget y portal, con
    y sin `curl_cffi`) y es la opción mantenida.
  - Fijar la versión evita que una versión nueva cambie el login sin que nos enteremos.
- **Alternatives considered**:
  - `garth`: obsoleto y sin logins nuevos.
  - Implementar el SSO de Garmin a mano: frágil y fuera del alcance (constitución X).
  - El envoltorio `Garmin`: retiene la contraseña en memoria (FR-003).

## R2. Interfaz `GarminClient`

- **Decision**: un `Protocol` en `src/garmin_hub/garmin/client.py` con resultados y errores
  propios, sin tipos de la librería (contrato completo en
  [contracts/garmin-client.md](contracts/garmin-client.md)):
  - `start_login(email, password) -> LoginSucceeded | MfaPending`;
  - `complete_mfa(pending, code) -> LoginSucceeded`;
  - `verify(tokens) -> VerifyResult`, que comprueba el acceso sin descargar datos y devuelve los
    accesos renovados si la librería los ha refrescado.
  - Errores: `InvalidCredentials`, `InvalidMfaCode`, `RateLimited`, `TemporarilyBlocked`,
    `GarminUnavailable`, `TokenRejected` y `GarminProtocolError`.
  - Implementaciones: `GarminConnectClient` (real) y `FakeGarminClient` (tests y demo).
- **Rationale**: la constitución III y VII exige que la librería pueda sustituirse. Los errores
  propios permiten mapear cada caso a un mensaje y a un efecto sobre el estado (R10) sin
  depender del texto de las excepciones de la librería.
- **Alternatives considered**: exponer el `Client` de la librería a los servicios (acopla todo a
  una librería no oficial).

## R3. Intento pendiente de MFA

- **Decision**: el intento pendiente de MFA se guarda **en la memoria del proceso web**, en un
  `PendingLoginRegistry` (`src/garmin_hub/garmin/pending.py`).
  - Cada entrada tiene: un identificador aleatorio (`secrets.token_urlsafe(16)`), el `user_id`,
    el propósito (`link` o `reauth`), el `garmin_account_id` si es una reautenticación, el alias si
    es una vinculación, el objeto de la librería que espera el código, la fecha de caducidad y el
    número de códigos fallidos.
  - Caduca a los `GARMIN_HUB_GARMIN_MFA_TTL_MINUTES` (5). Se purga al consultar el registro. Se
    descarta al completarse, al cancelarse o al empezar otro intento el mismo usuario, porque
    cada usuario tiene como máximo un intento pendiente.
  - El registro tiene un tope global de entradas (100). Si se alcanza, el intento nuevo se
    rechaza como "Garmin no está disponible; inténtalo más tarde".
  - Si el proceso se reinicia, o la petición del código llega a otro proceso, el intento no se
    encuentra y se trata como caducado: "El intento ha caducado; vuelve a empezar".
  - `web serve` ya ejecuta un único proceso uvicorn (feature 001). La feature de despliegue
    (011) debe mantener un solo proceso web o usar afinidad de sesión.
- **Rationale**:
  - En `garminconnect` 0.3.17, `resume_login(client_state, code)` ignora `client_state`. El estado
    del MFA vive en atributos privados del objeto `Client`: `_mfa_session` (una sesión HTTP viva
    de `requests` o de `curl_cffi`, con sus cookies), `_mfa_login_params`, `_mfa_flow`, etc.
  - Serializarlo en la base de datos obligaría a reconstruir a mano esas sesiones para cada una
    de las 5 estrategias, a partir de atributos privados que cambian entre versiones.
  - El estado es efímero (5 minutos) y perderlo solo obliga al usuario a repetir el login. Además,
    no contiene la contraseña: la librería no la guarda en el objeto (comprobado en el código de
    la versión 0.3.17).
- **Alternatives considered**:
  - Serializar cookies y parámetros en una tabla cifrada: frágil y dependiente de la
    implementación interna.
  - Mantener abierta la petición HTTP del login mientras el usuario escribe el código: imposible
    con formularios normales y sin estado.
  - Fijar `prompt_mfa` con una cola entre hilos: igual de dependiente del proceso y más compleja.
- **Constitución VII (v1.1.0)**: es el caso que permite la excepción de estado efímero de un
  handshake de autenticación. Cumple sus condiciones:
  - dura 5 minutos, por debajo del máximo de 10;
  - no contiene la contraseña ni el correo;
  - perderlo solo obliga a repetir el login;
  - el plan exige un único proceso web o afinidad de sesión.

## R4. Identidad de la cuenta en Garmin

- **Decision**:
  - Tras un login correcto se pide `GET /userprofile-service/socialProfile` (la misma llamada
    ligera que usa la librería para verificar el acceso) y se toma `profileId` (entero) como
    identidad.
  - Se guarda en claro en `garmin_account.garmin_profile_id` (`BIGINT`). Nunca se muestra en la
    interfaz, ni se escribe en logs o en auditoría, ni se exporta.
  - Si la respuesta no trae un `profileId` entero, se lanza `GarminProtocolError` y no se vincula
    nada.
- **Rationale**:
  - `profileId` es estable y no depende del correo, que no se guarda (FR-028a).
  - Guardarlo en claro permite los índices únicos filtrados de FR-007.
- **Alternatives considered**:
  - Un HMAC del `profileId`, como el correo en `login_attempt`: la rotación del secreto cambiaría
    todos los HMAC y rompería la unicidad.
  - `displayName`: Garmin permite cambiarlo.
  - El correo: no se guarda.

## R5. Cifrado de los accesos y rotación de la clave

- **Decision**:
  - El cifrado usa `cryptography.fernet.Fernet`, con un `TokenCipher` en
    `src/garmin_hub/security/token_cipher.py`.
  - El secreto obligatorio `GARMIN_HUB_MASTER_KEYS` tiene el formato
    `<versión>:<clave>[,<versión>:<clave>...]`. Las versiones son enteros positivos y únicos, y la
    clave vigente es la de versión más alta.
  - El nombre es el que ya anticipaba la feature 001 (research R13 de 001 y `.env.example`).
    `GARMIN_HUB_RAW_DIR` sigue aplazado hasta la feature que guarde ficheros crudos, porque esta no
    los usa.
  - Al cifrar se usa la clave vigente y se guarda su número en `garmin_token.key_version`. Al
    descifrar se usa la clave de la versión de la fila.
  - Si esa versión ya no está configurada, o Fernet lanza `InvalidToken`, la cuenta pasa a "Error"
    con `error_code='token_undecryptable'` (FR-017). El contenido cifrado nunca se muestra ni se
    registra.
  - `load_secrets` exige `GARMIN_HUB_MASTER_KEYS` y valida su formato y cada clave (32 bytes en
    base64 url-safe). Si falta, el CLI devuelve el código 2 nombrando la variable; si no es
    válido, devuelve el código 2 con la variable en la lista de "no válidos" (FR-027). Nunca se
    muestra ningún valor.
  - Lo que se cifra es exactamente el JSON de `Client.dumps()`, es decir, el token de acceso, el
    de renovación y el identificador de cliente de Garmin (OAuth DI).
  - Si `dumps()` no contiene un token de renovación (la librería ha entrado por el camino
    alternativo `JWT_WEB`, que no se puede persistir), se lanza `GarminProtocolError` y no se
    vincula nada.
  - Comandos nuevos (ver [contracts/cli.md](contracts/cli.md)):
    - `garmin-hub key generate`: imprime una clave nueva. No necesita secretos.
    - `garmin-hub key reencrypt`: vuelve a cifrar con la clave vigente los accesos que usan
      versiones antiguas.
  - Flujo de rotación: añadir la versión nueva, reiniciar, ejecutar `key reencrypt` y retirar la
    versión antigua.
- **Rationale**: lo exige la constitución IV (Fernet + `key_version`), y la Assumption de la spec
  dice que una versión anterior se puede seguir descifrando mientras esté configurada.
- **Alternatives considered**:
  - `MultiFernet`: prueba las claves en orden, pero no registra qué versión se usó, que es lo que
    pide la constitución.
  - Un secreto por versión (`GARMIN_HUB_TOKEN_KEY_1`, ...): enumerarlos es más incómodo de
    configurar.

## R6. Una petición en curso por cuenta y límite de comprobaciones

- **Decision**:
  - La columna `garmin_account.request_lease_until` hace de candado por cuenta, garantizado en la
    base de datos (constitución III).
  - Antes de cualquier petición a Garmin sobre una cuenta existente (comprobar, reautenticar o
    completar su MFA), se ejecuta un `UPDATE ... SET request_lease_until = now + lease WHERE
    garmin_account_id = ? AND (request_lease_until IS NULL OR request_lease_until < now)`.
  - Si no se actualiza ninguna fila, la acción se rechaza con "Hay otra operación en curso con
    esta cuenta; inténtalo en unos segundos." Al terminar, haya ido bien o mal, se libera con
    `request_lease_until = NULL`.
  - La duración del candado es `GARMIN_HUB_GARMIN_REQUEST_LEASE_SECONDS` (120), mayor que el
    tiempo máximo de una petición. Así, un proceso caído no deja la cuenta bloqueada para
    siempre.
  - La comprobación (FR-025) se reclama además con `last_check_started_at`, con la condición
    `IS NULL OR <= now - GARMIN_HUB_GARMIN_CHECK_INTERVAL_SECONDS (60)`. Si no se puede reclamar,
    el usuario ve "Ya se ha comprobado hace menos de un minuto."
  - **Todas las escrituras que siguen a una llamada a Garmin son condicionales**, para evitar la
    carrera con una desvinculación (FR-021):
    - el `UPDATE` de la cuenta lleva `WHERE garmin_account_id = ? AND status IN ('valid',
      'reauth_required', 'error')`;
    - el token solo se guarda si ese `UPDATE` ha afectado a una fila.
    - Si la cuenta se ha desvinculado mientras tanto, el resultado de Garmin se descarta y el
      usuario ve "La cuenta ha cambiado mientras se comprobaba; recarga la página."
  - La desvinculación y el borrado de datos también reclaman el candado. Si está ocupado,
    responden 409 con el mensaje de arriba.
  - **`last_checked_at`** (FR-024) se actualiza solo cuando la comprobación tiene un resultado
    definitivo: `ok`, `token_rejected`, `identity_mismatch` o `token_undecryptable`. Con un error
    transitorio no se actualiza, porque no se ha podido comprobar nada; el usuario ve el mensaje
    de R10.
  - El worker de sincronización (feature posterior) usará el mismo candado en cada petición.
  - En la vinculación de una cuenta nueva todavía no hay fila que bloquear; los duplicados los
    evitan los índices únicos de R7.
- **Rationale**: un `UPDATE` condicional es atómico tanto en SQL Server como en SQLite y no
  necesita una tabla de trabajos, que todavía no existe (`sync_job` llega con la sincronización).
- **Alternatives considered**: `sp_getapplock` (exclusivo de SQL Server, no funciona en la
  comprobación rápida con SQLite); un candado en memoria (no lo garantiza la base de datos).

## R7. Unicidad: identidad, alias y recuperación

- **Decision**: tres índices únicos filtrados en `garmin_account`, declarados con `mssql_where` y
  `sqlite_where`:
  - `UX_garmin_account_profile_active (garmin_profile_id) WHERE status IN ('valid',
    'reauth_required', 'error')`: una sola vinculación activa por cuenta Garmin (FR-007).
  - `UX_garmin_account_user_profile (user_id, garmin_profile_id) WHERE status IN ('valid',
    'reauth_required', 'error', 'unlinked')`: como mucho una fila viva por usuario y cuenta
    Garmin, que es la que se recupera al volver a vincular (FR-005, US5-4).
  - `UX_garmin_account_user_alias (user_id, alias_key) WHERE status IN ('valid', 'reauth_required',
    'error', 'unlinked')`: alias único por usuario sin distinguir mayúsculas (FR-006).
    `alias_key = alias.strip().casefold()`.
  - Las filas en `deleting` quedan fuera de los tres índices. Así, una cuenta Garmin cuyos datos
    se están borrando se puede volver a vincular, y crea una fila nueva.
- **Orden de la vinculación**, una vez que Garmin acepta el login:
  1. Se bloquea la fila del usuario (`lock_user` de 001, que usa `UPDLOCK`).
  2. Si el usuario ya tiene esa identidad en un estado activo, se rechaza indicando el alias
     (US1-7).
  3. Si la tiene en `unlinked`, se recupera esa fila: mismo identificador y datos. Se ignora el
     alias escrito y se mantiene el original, porque el alias no se puede editar en esta
     feature. El usuario ve "Se ha recuperado la cuenta «alias» con sus datos."
  4. Si no la tiene, se valida que el alias no esté en uso y que no se supere el máximo de
     cuentas (R8), y se inserta la fila.
  5. Si el índice de identidad activa falla (`IntegrityError`), es que otro usuario la tiene
     vinculada. Se rechaza con "Esta cuenta Garmin ya está vinculada a otro usuario de
     garmin-hub.", sin decir a cuál (FR-007).
  - Antes del login solo se valida el formato del alias (de 1 a 50 caracteres sin espacios
    alrededor), porque su unicidad depende de si se recupera una cuenta.
- **Rationale**: la base de datos garantiza la unicidad aunque haya dos peticiones a la vez (caso
  límite "dos usuarios vinculan a la vez"). SQLite admite índices parciales, así que la
  comprobación rápida cubre la lógica; el test de concurrencia real lleva la marca `mssql`.
- **Alternatives considered**: comprobar antes de insertar sin índice (hay una condición de
  carrera); una tabla aparte para las identidades (es más complejo y no aporta nada).

## R8. Máximo de cuentas por usuario

- **Decision**:
  - El máximo es `GARMIN_HUB_GARMIN_MAX_ACCOUNTS` (10). Cuentan las cuentas en `valid`,
    `reauth_required` y `error`, que son las que generan tráfico con Garmin. Las `unlinked` no
    cuentan.
  - El recuento se hace con la fila del usuario bloqueada (R7, paso 1).
  - La comprobación se hace dos veces: antes del login, para no molestar a Garmin en vano, y
    otra vez dentro de la transacción.
  - Recuperar una cuenta `unlinked` también cuenta, porque vuelve a estar activa.
- **Rationale**: es la lectura más útil del límite, y la Assumption correspondiente se
  documenta en el plan.
- **Alternatives considered**: contar también las `unlinked` (castigaría conservar datos).

## R9. Límite de intentos de vinculación y reautenticación

- **Decision**:
  - Una tabla `garmin_login_failure (user_id, failed_at)` y la regla de
    `GARMIN_HUB_GARMIN_LOGIN_MAX_FAILURES` (5) fallos por usuario en
    `GARMIN_HUB_GARMIN_LOGIN_WINDOW_MINUTES` (15).
  - Cuentan como fallo las credenciales incorrectas y los códigos MFA incorrectos, que son los
    rechazos de Garmin que pueden provocar un bloqueo en su lado.
  - No cuentan los errores transitorios ni los rechazos locales (alias, duplicado o máximo de
    cuentas).
  - La comprobación se hace **antes** de llamar a Garmin. Si se supera, se responde sin contactar
    con Garmin: "Has hecho demasiados intentos con Garmin; espera unos minutos."
  - Las filas de más de 24 horas se purgan de forma oportunista, como `login_attempt`.
- **Rationale**: el límite es por usuario (lo pide FR-010) y no por correo ni por origen. Reusar
  `login_attempt` obligaría a cambiar su `CHECK` de `kind` y a mezclar dos semánticas distintas.
- **Alternatives considered**: ampliar `login_attempt` con un `kind` nuevo (descartado por lo
  anterior).

## R10. Errores de Garmin: mensaje y efecto sobre el estado

| Error de `GarminClient` | Origen en la librería | Mensaje (FR-026) | Efecto |
|---|---|---|---|
| `InvalidCredentials` | `GarminConnectAuthenticationError` en `login` | "Garmin no acepta ese correo o contraseña." | Cuenta fallo (R9); no cambia ninguna cuenta |
| `InvalidMfaCode` | `GarminConnectAuthenticationError` en `resume_login` | "El código de verificación no es correcto." | Cuenta fallo; el intento sigue vivo hasta que caduca |
| (intento no encontrado) | — | "El intento ha caducado; vuelve a empezar." | — |
| `RateLimited` | `GarminConnectTooManyRequestsError` (429), en el login o en `verify` | "Garmin está limitando las peticiones; inténtalo dentro de un rato." | Transitorio: no cambia el estado (FR-017) |
| `TemporarilyBlocked` | en el login, una respuesta HTTP 403 de los endpoints de SSO (desafío de Cloudflare o bloqueo de la cuenta). Se detecta por `exc.response.status_code == 403` o, si no hay respuesta, por el patrón `\b403\b` en el texto de `GarminConnectConnectionError`; ese texto solo se usa para clasificar, nunca se muestra ni se registra | "Garmin ha bloqueado temporalmente el inicio de sesión; inténtalo más tarde." | Transitorio |
| `GarminUnavailable` | errores de red o de tiempo de espera, 5xx | "No se ha podido conectar con Garmin; inténtalo más tarde." | Transitorio |
| `TokenRejected` | 401 o 403 de la API tras renovar | "Garmin ya no acepta el acceso guardado; vuelve a autenticar la cuenta." | `reauth_required` (FR-016) |
| `GarminProtocolError` | respuesta inesperada, sin `profileId`, sin token persistible | "Garmin ha respondido de forma inesperada; inténtalo más tarde." | Al vincular, no se crea nada. En una cuenta existente, transitorio |
| (descifrado imposible) | `TokenCipher` | "No se puede usar el acceso guardado; vuelve a autenticar la cuenta." | `error` con `token_undecryptable` |
| (identidad distinta en `verify`) | `profileId` distinto del guardado | "El acceso guardado corresponde a otra cuenta Garmin; vuelve a autenticarla." | `error` con `identity_mismatch` |

- La reautenticación con una identidad distinta (US4-2) se rechaza con "Esas credenciales son de
  otra cuenta Garmin distinta de «alias»." La cuenta no cambia y el fallo no cuenta para el
  límite de R9.
- El mapeo de la librería a los errores propios se hace por tipo de excepción y, si hace falta,
  por el código HTTP de `exc.response`, nunca mostrando su texto.
- **Rationale**: un único punto de mapeo hace los mensajes comprobables y evita que el texto de
  Garmin llegue a la interfaz o a los logs.

## R11. Reintentos y pausas con Garmin

- **Decision**:
  - **Login, MFA y reautenticación** (constitución III v1.1.0): `GarminConnectClient` no deja que
    la librería encadene sus 5 estrategias sin control, y recorre las estrategias él mismo:
    - **Orden**: `mobile+cffi`, `mobile+requests`, `widget+cffi`, `portal+cffi` y
      `portal+requests`. Para cada una llama a `Client.login(...)` con `skip_strategies` igual a
      todas las demás.
    - **Siguiente estrategia**: solo se pasa a ella tras un fallo que no sea de credenciales, ni de
      MFA, ni 429, ni 403. Antes de pasar se espera
      `GARMIN_HUB_GARMIN_LOGIN_STRATEGY_PAUSE_SECONDS` (2 s, jitter de ±50 %).
    - **Paradas**: se detiene ante el primer 429 (`RateLimited`), el primer 403
      (`TemporarilyBlocked`), unas credenciales rechazadas o una petición de MFA.
    - **Tiempo máximo**: `GARMIN_HUB_GARMIN_LOGIN_BUDGET_SECONDS` (45). Si se agota antes de
      probar la siguiente estrategia, se lanza `GarminUnavailable`.
    - **Reintentos del login completo**: ante 429 o 5xx, hasta
      `GARMIN_HUB_GARMIN_LOGIN_MAX_RETRIES` (0 por defecto, porque lo pide un caso límite de la
      spec), con el backoff de `verify`.
    - **MFA**: `resume_login` es una sola petición y no se reintenta.
  - **`verify`**: la llamada a `socialProfile` se reintenta ante 429, 5xx o un error de red, con
    backoff exponencial y jitter: espera base de 1 s, factor 2, jitter de ±50 % y como máximo
    `GARMIN_HUB_GARMIN_MAX_RETRIES` (2) reintentos. Agotados los reintentos, se lanza el error
    transitorio correspondiente.
  - Las esperas usan un `sleep` inyectable, que en los tests no duerme.
- **Rationale**: la constitución III exige pausas con jitter, backoff con un límite configurable
  y cortar el login ante el primer 429. La spec fija el límite por defecto en 0, porque reintentar
  un login rechazado es justo lo que provoca bloqueos. El tiempo máximo protege SC-001.
- **Alternatives considered**:
  - dejar la cascada interna de la librería: continúa tras un 429 sin pausas e incumple III;
  - usar una sola estrategia: menos robusto ante los cambios de Garmin.

## R12. Ejecución de las llamadas a Garmin en la web

- **Decision**:
  - Las rutas que llaman a Garmin son `def` y se ejecutan en el pool de hilos de Starlette, como
    las de 001.
  - La llamada a Garmin se hace **fuera** de cualquier transacción, para no tener filas
    bloqueadas mientras Garmin responde. El orden es:
    1. una transacción corta para reclamar el candado o validar;
    2. la llamada a Garmin;
    3. una transacción corta para guardar el resultado y liberar el candado.
  - Los tiempos de espera de red los fija la librería: 15 s por petición.
- **Rationale**: con decenas de usuarios basta el pool de hilos, y las transacciones cortas
  evitan bloqueos largos en SQL Server.
- **Tiempo de respuesta**: el tiempo máximo del login (R11, 45 s) se comprueba entre
  estrategias. Una petición en curso puede añadir hasta 15 s, así que el peor caso queda en torno
  a 1 minuto, y el caso normal (primera estrategia correcta) en 2–10 s. SC-001 se mide en el test
  `live` y en la validación final.

## R13. Aviso de datos versionado

- **Decision**:
  - La constante `NOTICE_VERSION = 1` está en `src/garmin_hub/garmin_accounts/notice.py`. El texto
    está en la plantilla `web/templates/garmin/notice_v1.html`.
  - Cambiar el texto obliga a crear `notice_v2.html` y subir la constante. Un test comprueba que
    existe la plantilla de la versión vigente.
  - La tabla `data_notice_acceptance` tiene la clave primaria `(user_id, notice_version)` y
    registra `accepted_at`. Aceptar dos veces la misma versión es idempotente.
  - **Vincular y reautenticar** exigen haber aceptado la versión vigente. Si no se ha aceptado,
    `GET /cuentas-garmin/vincular` redirige al aviso con `next`.
  - **Página de inicio**: muestra el aviso "Hay una versión nueva del aviso de datos" si el
    usuario tiene al menos una cuenta en `valid`, `reauth_required` o `error` y no ha aceptado la
    versión vigente (FR-012). No detiene nada.
- **Rationale**: el texto queda versionado junto con el código, y la versión aceptada es un
  número auditable.
- **Alternatives considered**: guardar el texto en la base de datos (necesitaría una pantalla de
  edición que nadie ha pedido); usar un hash del texto como versión (cualquier retoque de
  formato obligaría a aceptarlo de nuevo).

## R14. Desvinculación y borrado de una cuenta

- **Decision**:
  - **Candado**: las dos opciones reclaman antes el candado de R6 y lo liberan al terminar.
  - **Conservar datos**: en una transacción se borra `garmin_token`, el estado pasa a `unlinked`,
    se pone `unlinked_at` y se libera el candado. El intento pendiente del registro en memoria,
    si existe, se descarta.
  - **Borrar datos**: en una transacción se borra `garmin_token`, el estado pasa a `deleting` y se
    pone `deletion_requested_at`. Después se ejecutan los pasos de un registro nuevo,
    `register_account_deletion_step(name, order, fn(ctx, garmin_account_id))`, en
    `src/garmin_hub/garmin_accounts/deletion.py`, y el último paso borra la fila.
    - En esta feature los pasos son `garmin_token` (idempotente) y `garmin_account_row`.
    - Las features de datos y de ficheros crudos añadirán los suyos antes del último.
    - Si un paso falla, la cuenta queda en `deleting`. El listado la muestra como "Borrando
      datos… (no se pudo completar)" con un botón "Reintentar" (FR-022).
  - Una cuenta `unlinked` puede pasar después a `deleting` (US5-5).
  - **Borrado del usuario** (FR-029): se registra un paso de 001 (`register_deletion_step`)
    llamado `garmin_accounts`, con orden 50. Ejecuta el borrado de cada cuenta del usuario y
    después borra sus filas de `data_notice_acceptance` y `garmin_login_failure`. Es idempotente.
- **Rationale**: sigue el mismo patrón reanudable que el borrado de usuario de 001 (R16), a nivel
  de cuenta.
- **Alternatives considered**: `ON DELETE CASCADE` (no cubre los ficheros crudos ni deja
  reanudar el borrado).

## R15. Autorización y respuestas indistinguibles

- **Decision**:
  - La dependencia nueva `require_regular_user` envuelve `require_user` y responde `404` si
    `role='admin'` (FR-009, FR-015 y US3-3). Se aplica a todo el router `/cuentas-garmin`.
  - El `{account_id}` de las rutas se recibe como `str` y se interpreta a mano. Si no es un UUID
    válido, si no existe o si es de otro usuario, la respuesta es **la misma**: `404` con la
    página genérica de 001 (FR-014, SC-004).
  - Todas las consultas filtran por `garmin_account_id` **y** `user_id`, en una única función
    `get_own_account(conn, user_id, account_id)`.
  - Las cuentas en `deleting` solo admiten "Reintentar". El resto de acciones responden `409`
    con un mensaje.
  - Esta feature no expone datos de atleta, así que `can_view` (constitución VI) se crea con la
    feature de clubes y consentimiento.
- **Rationale**: denegación por defecto en un único punto, y ninguna diferencia observable entre
  "no existe" y "no es tuya".

## R16. Tests

- **Decision**:
  - **Unitarios** (sin red): `TokenCipher` (cifrado, versión, rotación y claves no válidas),
    análisis de `GARMIN_HUB_MASTER_KEYS`, mapeo de errores de la librería con excepciones
    sintéticas, `PendingLoginRegistry` (caducidad, un intento por usuario y tope), validación del
    alias y la regla de backoff de R11.
  - **Integración** (`integration`, con `FakeGarminClient`):
    - flujos US1–US7;
    - matriz de autorización: otro usuario, un administrador, un UUID mal formado y uno
      inexistente, comparando estado y cuerpo de la respuesta;
    - unicidad y recuperación;
    - candado y límite de comprobación;
    - límite de intentos;
    - borrado reanudable con un paso que falla;
    - borrado del usuario y exportación;
    - migración `0002` arriba y abajo;
    - auditoría con la lista blanca de claves.
  - **Sin secretos (SC-002)**: un test de integración vincula, reautentica, comprueba y
    desvincula con un correo, una contraseña, un código MFA, unos accesos y un `profileId`
    centinela. Después
    recorre todas las columnas de texto y binarias del schema y los logs capturados, y comprueba
    que no aparece ningún centinela en claro. La única excepción es el `profileId` en
    `garmin_account.garmin_profile_id`, que tampoco puede aparecer en `audit_event.details`, en
    los logs ni en las respuestas (FR-028a).
  - **Concurrencia** (`mssql`): dos hilos vinculan la misma identidad a la vez y solo uno lo
    consigue.
  - **Live** (`live`, excluido por defecto): `tests/live/test_garminconnect_client.py` hace un
    login real, `verify` y, si la cuenta tiene MFA, el flujo con código introducido por consola.
    Usa `GARMIN_HUB_LIVE_GARMIN_EMAIL` y `GARMIN_HUB_LIVE_GARMIN_PASSWORD` del entorno del
    desarrollador, nunca del repositorio.
  - **Estructura**: un test comprueba que solo `garmin/garminconnect_client.py` importa
    `garminconnect` o `curl_cffi`.
- **Rationale**: cumple la constitución IX (los unitarios no usan red y lo `live` se excluye) y
  convierte en tests SC-002, SC-003 y SC-004.

## R17. Logs de la librería

- **Decision**:
  - Los loggers `garminconnect` y `curl_cffi` se configuran en `ERROR`, y además llevan un filtro
    propio, `ThirdPartyLogScrubber`:
    - sustituye `msg` por el texto fijo `"third-party library error (details suppressed)"`;
    - vacía `args`, `exc_info` y `stack_info`;
    - conserva solo el nombre del logger y el nivel.
  - El `RedactingFilter` de 001 sigue aplicándose después.
  - El código propio nunca incluye en un log el texto de una excepción de la librería. Solo
    registra el tipo de error propio (R10) y el `garmin_account_id`.
  - Un test emite un error sintético de la librería con una contraseña, un correo, un token y un
    `profileId` centinela, también en `args` y en `exc_info`. Comprueba que no llega ninguno a los
    ficheros de log y que sí aparece el texto fijo.
- **Rationale**: la librería registra avisos con URL y cuerpos parcialmente saneados, y la
  constitución IV prohíbe datos personales y tokens en los logs.

## R18. Cliente falso para desarrollo

- **Decision**:
  - `GARMIN_HUB_GARMIN_CLIENT=garminconnect|fake` (`garminconnect` por defecto). `fake` solo se
    acepta con `GARMIN_HUB_ENV=dev` o `test`; en `prod`, la configuración se rechaza con el código
    2.
  - El comportamiento de `FakeGarminClient` está en
    [contracts/garmin-client.md](contracts/garmin-client.md). Por ejemplo, los correos
    `mfa+...@example.test` piden MFA con el código `123456`.
- **Rationale**: permite el quickstart manual y la demo sin cuentas reales y sin red.
- **Alternatives considered**: hacer la demo solo con una cuenta real (no se podría repetir, y
  arriesga bloqueos).

## R19. Dependencias nuevas

| Dependencia | Uso | Justificación (constitución X) |
|-------------|-----|--------------------------------|
| `cryptography` | Fernet (R5) | La exige la constitución IV; es la implementación de referencia |
| `garminconnect==0.3.17` | acceso a Garmin (R1) | La librería no oficial mantenida; solo se usa detrás de `GarminClient` |
| (transitivas) `curl_cffi`, `requests`, `ua-generator` | estrategias de login de la librería | Llegan con `garminconnect`; no se importan directamente |

No se añaden librerías de tareas, de colas ni de caché.
