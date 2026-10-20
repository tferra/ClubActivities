# Data Model: Vinculación y gestión de cuentas Garmin (002)

Se aplican las convenciones de la feature 001:
- schema `GARMIN_HUB_DB_SCHEMA`;
- marcas de tiempo `DATETIME2(3)` en UTC;
- UUID generados en la aplicación;
- cambios solo mediante Alembic.

La migración `0002_garmin_accounts` (`down_revision = "0001_user_access"`) crea todo lo que se
describe aquí, y su `downgrade` lo elimina.

**Lo que no hay en el modelo**:
- No hay ninguna columna para la contraseña ni para el correo de Garmin (FR-003, FR-028a,
  constitución IV).
- El intento pendiente de MFA no es una tabla: vive en la memoria del proceso web (research R3).

## garmin_account

Cuenta Garmin vinculada a un usuario (FR-005, FR-013).

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| garmin_account_id | UNIQUEIDENTIFIER | PK (uuid4). Es estable: se conserva al reautenticar y al recuperar la cuenta (FR-005) |
| user_id | UNIQUEIDENTIFIER | NOT NULL, FK → app_user (NO ACTION) |
| alias | NVARCHAR(50) | NOT NULL, de 1 a 50 caracteres sin espacios alrededor (FR-006) |
| alias_key | NVARCHAR(50) | NOT NULL; `alias.strip().casefold()` |
| garmin_profile_id | BIGINT | NOT NULL; `profileId` de Garmin (R4). Nunca se muestra, ni va a logs, auditoría o exportación |
| status | VARCHAR(20) | NOT NULL, CHECK IN (`valid`, `reauth_required`, `error`, `unlinked`, `deleting`) |
| error_code | VARCHAR(32) | NULL; CHECK IN (`token_undecryptable`, `identity_mismatch`); NOT NULL si y solo si `status='error'` |
| linked_at | DATETIME2(3) | NOT NULL; primera vinculación |
| last_login_at | DATETIME2(3) | NOT NULL; último login correcto en Garmin |
| last_sync_at | DATETIME2(3) | NULL; siempre NULL en esta feature ("Nunca") |
| last_checked_at | DATETIME2(3) | NULL; última comprobación terminada |
| last_check_started_at | DATETIME2(3) | NULL; reclamación de la comprobación, una por minuto (R6) |
| request_lease_until | DATETIME2(3) | NULL; candado de una petición en curso por cuenta (R6) |
| unlinked_at | DATETIME2(3) | NULL; NOT NULL si `status='unlinked'` |
| deletion_requested_at | DATETIME2(3) | NULL; NOT NULL si `status='deleting'` |
| created_at | DATETIME2(3) | NOT NULL |
| updated_at | DATETIME2(3) | NOT NULL |

**Índices** (R7). Los filtrados usan `mssql_where` y `sqlite_where`:
- `UX_garmin_account_profile_active` (garmin_profile_id) WHERE `status IN ('valid',
  'reauth_required', 'error')`.
- `UX_garmin_account_user_profile` (user_id, garmin_profile_id) WHERE `status IN ('valid',
  'reauth_required', 'error', 'unlinked')`.
- `UX_garmin_account_user_alias` (user_id, alias_key) WHERE `status IN ('valid',
  'reauth_required', 'error', 'unlinked')`.
- `IX_garmin_account_user` (user_id, created_at).

**Restricción CHECK** `CK_garmin_account_status_fields`, que exige la coherencia entre `status`,
`error_code`, `unlinked_at` y `deletion_requested_at` descrita en la tabla.

**Reglas**
- Solo pueden ser propietarios los usuarios con `role='user'`. Lo valida el servicio, porque un
  CHECK entre tablas no es posible (FR-009).
- Máximo de `GARMIN_HUB_GARMIN_MAX_ACCOUNTS` (10) cuentas por usuario en `valid`,
  `reauth_required` o `error` (R8).
- Un usuario `deactivated` no puede gestionar ni comprobar sus cuentas porque no tiene sesión
  (feature 001). Las features de sincronización deben ignorar sus cuentas.

**Transiciones de `status`**

```
(login OK) ──► valid ◄──────────── reautenticación OK ────────────┐
                 │  ▲                                              │
  token rechazado│  │ reautenticación OK                           │
                 ▼  │                                              │
          reauth_required          descifrado imposible /          │
                 │                 identidad distinta              │
                 │      valid ─────────────────────────► error ────┘
                 │
  desvincular    │ (desde valid, reauth_required o error)
  ┌──────────────┴──────────────┐
  ▼ conservar                   ▼ borrar
unlinked ──borrar datos──► deleting ──pasos OK──► (fila eliminada)
  │                          ▲   │
  │ volver a vincular        └───┘ fallo → se queda; "Reintentar"
  │ (mismo usuario, misma identidad en Garmin)
  ▼
valid (mismo garmin_account_id)
```

- Los errores transitorios (R10) no cambian el estado (FR-017).
- La reautenticación se permite en `valid`, `reauth_required` y `error` (FR-018), no en
  `unlinked` ni en `deleting`.
- La comprobación se permite en `valid`, `reauth_required` y `error`.
- Cada cambio a `reauth_required` o a `error` se audita (`garmin.status_changed`).

## garmin_token

Acceso guardado (FR-004). Como máximo uno por cuenta.

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| garmin_account_id | UNIQUEIDENTIFIER | PK, FK → garmin_account (NO ACTION) |
| ciphertext | VARBINARY(MAX) | NOT NULL; Fernet sobre el JSON de `Client.dumps()` (R5) |
| key_version | INT | NOT NULL, CHECK `key_version > 0` |
| issued_at | DATETIME2(3) | NOT NULL; momento del login que lo obtuvo |
| updated_at | DATETIME2(3) | NOT NULL; última renovación o recifrado |

**Reglas**
- Existe solo si la cuenta está en `valid`, `reauth_required` o `error`. Se borra en la misma
  transacción que la desvinculación (FR-021).
- Solo se escribe si el `UPDATE` condicional de la cuenta (`status IN ('valid', 'reauth_required',
  'error')`) afecta a una fila (R6). Una cuenta desvinculada nunca recupera un token.
- Se reemplaza al reautenticar (FR-019). Si `verify` devuelve accesos renovados, se recifra con la
  clave vigente.
- `key reencrypt` lo reescribe con la clave vigente y actualiza `key_version`.
- Nunca se exporta (FR-030) y nunca se escribe en logs.

## data_notice_acceptance

Aceptación del aviso de datos (FR-011, FR-012).

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| user_id | UNIQUEIDENTIFIER | PK (1/2), FK → app_user (NO ACTION) |
| notice_version | INT | PK (2/2), CHECK `notice_version > 0` |
| accepted_at | DATETIME2(3) | NOT NULL |

**Reglas**
- La versión vigente es `NOTICE_VERSION`, que está en el código (R13).
- "Ha aceptado la vigente" significa que existe la fila `(user_id, NOTICE_VERSION)`.
- Se borra con el usuario y se exporta.

## garmin_login_failure

Fallos de login en Garmin por usuario (FR-010, R9).

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| failure_id | BIGINT IDENTITY | PK |
| user_id | UNIQUEIDENTIFIER | NOT NULL, FK → app_user (NO ACTION) |
| failed_at | DATETIME2(3) | NOT NULL |

**Índices**: `IX_garmin_login_failure_user` (user_id, failed_at).

**Reglas**
- Solo cuentan las credenciales incorrectas y los códigos MFA incorrectos.
- Las filas de más de 24 horas se purgan de forma oportunista.
- Se borra con el usuario y no se exporta, porque es un registro técnico, como `login_attempt`.

## Intento pendiente de MFA (en memoria, no es una tabla)

`PendingLogin` vive en el `PendingLoginRegistry` (R3) con estos campos:
- `attempt_id` (aleatorio);
- `user_id`;
- `purpose` (`link` | `reauth`);
- `garmin_account_id`, si es una reautenticación;
- `alias`, si es una vinculación;
- `mfa_required_at` y `expires_at`, que es el anterior + 5 minutos;
- `mfa_failures`;
- el objeto de la librería que espera el código.

No contiene ni la contraseña ni el correo. Hay como máximo un intento por usuario y un tope global
de 100.

## Relaciones

```
app_user 1 ─── * garmin_account 1 ─── 0..1 garmin_token
app_user 1 ─── * data_notice_acceptance
app_user 1 ─── * garmin_login_failure
audit_event ··· garmin_account (garmin_account_id en details, sin FK)
```

## Registros ampliables

- **Borrado de una cuenta**: `register_account_deletion_step(name, order, fn)`. Esta feature
  registra:
  - `garmin_token` (orden 10);
  - `garmin_account_row` (orden 1000, siempre el último).
- **Borrado de un usuario** (registro de 001): paso `garmin_accounts` (orden 50). Borra cada cuenta
  con los pasos anteriores y después `data_notice_acceptance` y `garmin_login_failure`.
- **Exportación** (registro de 001), con dos secciones:
  - `garmin_accounts`: `garmin_account_id`, `alias`, `status`, `linked_at`, `last_login_at`,
    `last_sync_at`, `last_checked_at`, `unlinked_at`;
  - `data_notice_acceptances`: `notice_version`, `accepted_at`.

## Configuración nueva (FR-002, FR-008, FR-010, FR-025)

| Variable | Valor por defecto |
|----------|-------------------|
| `GARMIN_HUB_GARMIN_MFA_TTL_MINUTES` | 5 |
| `GARMIN_HUB_GARMIN_MAX_ACCOUNTS` | 10 |
| `GARMIN_HUB_GARMIN_LOGIN_MAX_FAILURES` / `_WINDOW_MINUTES` | 5 / 15 |
| `GARMIN_HUB_GARMIN_CHECK_INTERVAL_SECONDS` | 60 |
| `GARMIN_HUB_GARMIN_REQUEST_LEASE_SECONDS` | 120 |
| `GARMIN_HUB_GARMIN_MAX_RETRIES` | 2 (verify) |
| `GARMIN_HUB_GARMIN_LOGIN_MAX_RETRIES` | 0 |
| `GARMIN_HUB_GARMIN_LOGIN_STRATEGY_PAUSE_SECONDS` | 2 |
| `GARMIN_HUB_GARMIN_LOGIN_BUDGET_SECONDS` | 45 |
| `GARMIN_HUB_GARMIN_CLIENT` | `garminconnect` (`fake` solo en `dev` y `test`) |

**Secreto nuevo obligatorio**: `GARMIN_HUB_MASTER_KEYS` (R5).
