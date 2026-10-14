# Data Model: Gestión de usuarios y acceso (001)

- Todas las tablas viven en el schema `GARMIN_HUB_DB_SCHEMA` (`gh` por defecto).
- Las marcas de tiempo son `DATETIME2(3)` en UTC.
- Los correos se guardan normalizados: sin espacios alrededor y en minúsculas (`str.strip().lower()`).
- La única forma de cambiar el esquema es una migración de Alembic: `0001_user_access` crea todo lo
  que se describe aquí.

## app_user

Usuario de la aplicación (FR-012).

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| user_id | UNIQUEIDENTIFIER | PK (uuid4 generado en la aplicación) |
| email | NVARCHAR(254) | NOT NULL, UNIQUE (`UX_app_user_email`), normalizado |
| display_name | NVARCHAR(100) | NOT NULL, de 1 a 100 caracteres sin espacios alrededor |
| password_hash | VARCHAR(255) | NOT NULL, argon2id |
| role | VARCHAR(16) | NOT NULL, CHECK IN (`user`, `admin`) |
| status | VARCHAR(20) | NOT NULL, CHECK IN (`active`, `deactivated`, `pending_deletion`) |
| created_at | DATETIME2(3) | NOT NULL |
| updated_at | DATETIME2(3) | NOT NULL |
| password_changed_at | DATETIME2(3) | NOT NULL |
| last_login_at | DATETIME2(3) | NULL |

**Reglas**
- `role` no cambia nunca tras el alta (FR-004a). Solo `admin create` crea usuarios con `admin`.
- Los usuarios `admin` no pueden tener cuentas Garmin ni membresías. Esta regla la harán cumplir
  las features de vinculación y clubes, con un CHECK o una validación del servicio.

**Transiciones de `status`**

```
(alta) ──► active ──desactivar──► deactivated ──reactivar──► active
              │                        │
              │ borrado propio         │ borrado por admin (solo role=user)
              ▼                        ▼
          pending_deletion ──pasos de borrado OK──► (fila eliminada)
              ▲      │
              └──────┘ fallo → se queda; "Reintentar"
```

- `active → deactivated` se rechaza si el usuario es el actor, o si es el último administrador
  activo (FR-027).
- `active → pending_deletion` se rechaza si es el último administrador activo.
- `deactivated → pending_deletion` solo ocurre por un administrador, solo si `role='user'` y con
  confirmación por correo (FR-028a).

## invitation

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| invitation_id | UNIQUEIDENTIFIER | PK |
| code_hash | BINARY(32) | NOT NULL, UNIQUE; `HMAC-SHA256(k_code, código)` |
| email | NVARCHAR(254) | NOT NULL, normalizado |
| note | NVARCHAR(200) | NULL |
| status | VARCHAR(16) | NOT NULL, CHECK IN (`pending`, `used`, `revoked`, `expired`) |
| created_at | DATETIME2(3) | NOT NULL |
| expires_at | DATETIME2(3) | NOT NULL, CHECK `expires_at > created_at` |
| created_by_user_id | UNIQUEIDENTIFIER | NULL, FK → app_user (NO ACTION) |
| used_at | DATETIME2(3) | NULL |
| used_by_user_id | UNIQUEIDENTIFIER | NULL, FK → app_user (NO ACTION) |
| revoked_at | DATETIME2(3) | NULL |
| revoked_by_user_id | UNIQUEIDENTIFIER | NULL, FK → app_user (NO ACTION) |

**Índices**
- `UX_invitation_pending_email` (email) WHERE `status='pending'` (FR-005a).
- `IX_invitation_created_at` (created_at DESC), para el listado.

**Reglas**
- El estado que se muestra se deriva así: si `status='pending'` y `expires_at <= ahora`, se
  muestra "caducada". Al crear una invitación nueva para un correo, sus pendientes caducadas se
  materializan como `expired` antes de insertar.
- Al crear la invitación se rechaza si el correo ya existe en `app_user`.
- El consumo es atómico (research R17). El paso de borrado de 001 pone a NULL las tres columnas
  `*_by_user_id` del usuario que se borra.

**Transiciones**: `pending → used | revoked | expired`. Son estados finales.

## password_reset_code

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| reset_id | UNIQUEIDENTIFIER | PK |
| user_id | UNIQUEIDENTIFIER | NOT NULL, FK → app_user (NO ACTION) |
| code_hash | BINARY(32) | NOT NULL, UNIQUE |
| status | VARCHAR(16) | NOT NULL, CHECK IN (`pending`, `used`, `superseded`, `expired`) |
| created_at | DATETIME2(3) | NOT NULL |
| expires_at | DATETIME2(3) | NOT NULL |
| created_by_user_id | UNIQUEIDENTIFIER | NULL (sin FK; solo es una referencia histórica) |
| used_at | DATETIME2(3) | NULL |

**Índices**
- `UX_reset_pending_user` (user_id) WHERE `status='pending'`.

**Reglas**
- Solo se genera si el usuario está `active` (US8, escenario 4).
- Al generar un código, el anterior pendiente pasa a `superseded` en la misma transacción.
- Al usarlo se comprueba `code_hash` y que el `user_id` corresponda al correo introducido. Si es
  así: `status='used'`, se cambia la contraseña y se borran todas las sesiones del usuario
  (FR-029).
- El paso de borrado de 001 elimina las filas del usuario.

## user_session

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| session_hash | BINARY(32) | PK; `HMAC-SHA256(k_session, id)` |
| user_id | UNIQUEIDENTIFIER | NOT NULL, FK → app_user (NO ACTION) |
| created_at | DATETIME2(3) | NOT NULL |
| last_seen_at | DATETIME2(3) | NOT NULL |
| expires_at | DATETIME2(3) | NOT NULL; `created_at` + duración máxima |

**Índices**
- `IX_user_session_user` (user_id), para invalidar todas las sesiones de un usuario.
- `IX_user_session_expires` (expires_at), para la purga.

**Reglas**
- Una sesión es válida si `now < expires_at`, si `now − last_seen_at < inactividad` y si
  `app_user.status = 'active'`.
- El token CSRF no se almacena: se deriva de la sesión (research R9).
- Las sesiones se borran al cerrar sesión, al desactivar al usuario, al cambiar la contraseña
  (todas menos la actual), al restablecerla (todas) y al pasar a `pending_deletion`.

## login_attempt

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| attempt_id | BIGINT IDENTITY | PK |
| attempted_at | DATETIME2(3) | NOT NULL |
| email_hmac | BINARY(32) | NULL; `HMAC(k_email_rl, correo)`; NULL en los canjes de código sin correo |
| ip | VARCHAR(45) | NOT NULL |
| kind | VARCHAR(20) | NOT NULL, CHECK IN (`login`, `code_redeem`, `current_password`) |
| succeeded | BIT | NOT NULL |

**Índices**
- `IX_login_attempt_email` (email_hmac, attempted_at).
- `IX_login_attempt_ip` (ip, attempted_at).

**Reglas**
- Reglas de límite en research R10.
- No contiene el correo en claro. Las filas de más de 24 horas se purgan de forma oportunista.

## audit_event

| Columna | Tipo | Restricciones |
|---------|------|---------------|
| audit_id | BIGINT IDENTITY | PK |
| occurred_at | DATETIME2(3) | NOT NULL |
| event_type | VARCHAR(64) | NOT NULL (catálogo en `contracts/audit-events.md`) |
| actor_user_id | UNIQUEIDENTIFIER | NULL, **sin FK** |
| subject_user_id | UNIQUEIDENTIFIER | NULL, **sin FK** |
| ip | VARCHAR(45) | NULL |
| details | NVARCHAR(1000) | NULL; JSON con claves en lista blanca, sin datos personales |

**Índices**
- `IX_audit_event_occurred` (occurred_at DESC).
- `IX_audit_event_subject` (subject_user_id, occurred_at).

**Reglas**
- Trigger `TR_audit_event_immutable` de tipo INSTEAD OF UPDATE, DELETE que hace
  `THROW 51000, 'audit_event is insert-only', 1`.
- Nunca guarda correos, nombres, contraseñas ni códigos. Tras borrar a un usuario solo quedan sus
  UUID (FR-035).

## Relaciones

```
app_user 1 ─── * user_session
app_user 1 ─── * password_reset_code
app_user 1 ─── * invitation (created_by / used_by / revoked_by, opcionales)
audit_event ··· app_user (referencias lógicas, sin FK)
login_attempt  (sin relación: está seudonimizada)
```

## Valores configurables (FR-002)

| Variable | Valor por defecto |
|----------|-------------------|
| `GARMIN_HUB_INVITE_TTL_DAYS` | 7 |
| `GARMIN_HUB_RESET_TTL_HOURS` | 24 |
| `GARMIN_HUB_SESSION_IDLE_MINUTES` | 30 |
| `GARMIN_HUB_SESSION_MAX_HOURS` | 12 |
| `GARMIN_HUB_LOGIN_PAIR_MAX_FAILURES` / `_WINDOW_MINUTES` | 5 / 15 |
| `GARMIN_HUB_LOGIN_IP_MAX_FAILURES` / `_WINDOW_MINUTES` | 20 / 15 |
| `GARMIN_HUB_LOGIN_EMAIL_SOFT_LIMIT` / `_WINDOW_MINUTES` / `_MAX_DELAY_SECONDS` | 50 / 60 / 10 |
