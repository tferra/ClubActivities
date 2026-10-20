# Contrato: eventos de auditoría (feature 002)

Amplía el catálogo de la feature 001 (`specs/001-user-access/contracts/audit-events.md`), sin
renombrar ni eliminar ningún evento.

En todos los eventos de esta tabla, `actor_user_id` y `subject_user_id` son el usuario
propietario, salvo los indicados como "NULL", e `ip_prefix` es la red reducida de la petición.

`details` **nunca** contiene:
- el correo, la contraseña o el `profileId` de Garmin;
- códigos MFA o accesos (cifrados o no);
- el alias, porque lo escribe el usuario y puede contener datos personales.

| event_type | details | Origen |
|------------|---------|--------|
| `garmin.notice_accepted` | `{"notice_version"}` | US6, FR-012 |
| `garmin.account_linked` | `{"garmin_account_id", "recovered": bool, "mfa": bool}` | US1, US5-4 |
| `garmin.link_failed` | `{"reason"}` (ver los motivos debajo) | US1, FR-028 |
| `garmin.reauthenticated` | `{"garmin_account_id", "mfa": bool}` | US4 |
| `garmin.reauth_failed` | `{"garmin_account_id", "reason"}` | US4 |
| `garmin.status_changed` | `{"garmin_account_id", "from", "to", "via": "check" \| "sync" \| "token_use", "error_code"?}` | FR-016, FR-017 |
| `garmin.account_checked` | `{"garmin_account_id", "result": "ok" \| "token_rejected" \| "transient" \| "error"}` | US7 |
| `garmin.account_unlinked` | `{"garmin_account_id", "data": "kept" \| "deleted"}` | US5 |
| `garmin.data_deletion_requested` | `{"garmin_account_id"}` | US5-5 (cuenta `unlinked`) |
| `garmin.account_deletion_step_failed` | `{"garmin_account_id", "step"}`. actor: NULL | FR-022 |
| `garmin.account_deleted` | `{"garmin_account_id", "steps"}` | FR-022, FR-029 |

**Valores de `reason`** en `link_failed` y `reauth_failed`:
- de Garmin: `bad_credentials`, `bad_mfa`, `mfa_expired`, `rate_limited`, `blocked`,
  `unavailable`, `protocol`;
- locales: `throttled` (límite de R9), `limit_reached`, `alias_taken`, `already_linked_self`,
  `linked_elsewhere`, `identity_mismatch` (solo en reautenticación) y `busy` (candado de R6).

**Notas**

- `via: "sync"` queda reservado para la feature de sincronización.
- `via: "token_use"` se usa cuando el descifrado del acceso falla al usarlo.
- `garmin.account_deleted` se emite también para cada cuenta que se borra con el usuario. En ese
  caso, el `user.deleted` de 001 recoge el paso `garmin_accounts`.
- La lista blanca `ALLOWED_DETAILS` de `accounts/audit.py` se amplía con estas claves, y un test
  verifica que ninguna otra llega a la tabla.
