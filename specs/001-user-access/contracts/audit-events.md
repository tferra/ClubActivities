# Contrato: eventos de auditoría (feature 001)

- Cada fila de `audit_event` tiene `event_type`, `actor_user_id`, `subject_user_id`, `ip_prefix`
  (red reducida, nunca la dirección completa) y `details` (JSON).
- `details` solo admite las claves listadas en esta tabla. **Nunca** contiene correos, nombres,
  contraseñas, códigos ni identificadores de sesión. Un test verifica esta lista blanca.

| event_type | actor | subject | details | Origen |
|------------|-------|---------|---------|--------|
| `admin.created` | NULL (CLI) | nuevo admin | `{"via": "cli"}` | `admin create` |
| `invitation.created` | admin | NULL | `{"invitation_id", "ttl_days"}` | US2 |
| `invitation.revoked` | admin | NULL | `{"invitation_id"}` | US6 |
| `user.signed_up` | nuevo usuario | nuevo usuario | `{"invitation_id"}` | US3 |
| `auth.login_succeeded` | usuario | usuario | `{}` | US4 |
| `auth.login_failed` | NULL | usuario si existe; si no, NULL | `{"reason": "bad_credentials" \| "blocked_pair" \| "blocked_ip" \| "inactive"}` | US4 |
| `auth.email_soft_limit` | NULL | usuario si existe; si no, NULL | `{"failures_1h"}` | FR-030a |
| `auth.code_redeem_failed` | NULL | NULL | `{"kind": "invitation" \| "reset", "reason": "invalid" \| "blocked_ip"}` | US3, US8 |
| `auth.logout` | usuario | usuario | `{}` | US4 |
| `user.name_changed` | usuario | usuario | `{}` | US5 |
| `user.data_exported` | usuario | usuario | `{"sections"}` | US5, FR-023a |
| `user.password_changed` | usuario | usuario | `{"sessions_closed"}` | US5 |
| `user.password_change_failed` | usuario | usuario | `{}` | US5 |
| `reset.created` | admin | usuario | `{"reset_id"}` | US8 |
| `reset.used` | usuario | usuario | `{"reset_id", "sessions_closed"}` | US8 |
| `user.deactivated` | admin | usuario | `{"sessions_closed", "resets_expired"}` | US6 |
| `user.reactivated` | admin | usuario | `{}` | US6 |
| `user.deletion_requested` | usuario o admin | usuario | `{"by": "self" \| "admin"}` | US7, FR-028a |
| `user.deletion_step_failed` | NULL | usuario | `{"step"}` | R16 |
| `user.deleted` | usuario o admin | usuario | `{"by": "self" \| "admin", "steps"}` | US7, FR-028a |

**Notas**

- En `auth.login_failed` con motivo `inactive`, el usuario ve el mismo mensaje genérico (FR-032).
  La auditoría sí distingue el motivo, porque solo la consulta el operador.
- Las features posteriores amplían este catálogo, por ejemplo con vinculaciones, solicitudes,
  consentimientos y lecturas de entrenadores. Ningún evento se renombra ni se elimina.
