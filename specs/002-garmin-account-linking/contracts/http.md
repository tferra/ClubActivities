# Contrato HTTP: cuentas Garmin (feature 002)

Se aplican las reglas generales de la feature 001 (`specs/001-user-access/contracts/http.md`):
- CSRF en todo POST mediante una dependencia de router;
- sin sesión, `303 → /login` (o `HX-Redirect` si la petición es HTMX);
- cabeceras de seguridad y `Cache-Control: no-store`;
- errores de validación con `422` y el formulario de nuevo;
- textos en español.

## Reglas propias

- **Usuarios normales**: todo el router `/cuentas-garmin` usa `require_regular_user`. Un
  administrador recibe `404` en cualquier ruta (FR-009, FR-015, US3-3) y no ve el enlace en el
  menú.
- **Cuentas ajenas** (FR-014, SC-004): si `{account_id}` no es un UUID válido, no existe o
  pertenece a otro usuario, la respuesta es `404` con la página genérica "No encontrado". El
  cuerpo es idéntico en los tres casos.
- **Datos sensibles**: los campos `garmin_email`, `garmin_password` y `mfa_code` nunca se
  devuelven en una respuesta, tampoco al volver a mostrar un formulario con error. Solo se
  conserva el `alias`.
- **Errores de Garmin** (research R10): se vuelve a mostrar el formulario con `422` y el mensaje
  de FR-026.
- **Límite de intentos**: con el límite superado (R9), la respuesta es `429` con "Has hecho
  demasiados intentos con Garmin; espera unos minutos." y sin contactar con Garmin.
- **Operación en curso**: si el candado de la cuenta está ocupado (R6), la respuesta es `409` con
  "Hay otra operación en curso con esta cuenta; inténtalo en unos segundos."

## Rutas

| Método | Ruta | Formulario | Éxito | Fallo |
|--------|------|------------|-------|-------|
| GET | `/cuentas-garmin` | — | 200. Listado con alias, estado, último login, última sincronización ("Nunca"), última comprobación y acciones según el estado (FR-013). Si no hay cuentas, mensaje y enlace para vincular (US2-3) | — |
| GET | `/cuentas-garmin/aviso?next=` | — | 200. Aviso de la versión vigente (`notice_v{N}.html`) con la casilla "He leído y acepto" | — |
| POST | `/cuentas-garmin/aviso` | `accept=1`, `next` | 303 → `next`, que solo admite rutas relativas bajo `/cuentas-garmin`; si no, → `/cuentas-garmin`. Registra la aceptación (idempotente) | 422 si falta `accept` |
| GET | `/cuentas-garmin/vincular` | — | 200, formulario (alias, correo y contraseña de Garmin). Si no ha aceptado el aviso vigente: 303 → `/cuentas-garmin/aviso?next=/cuentas-garmin/vincular` | 409 si ya tiene el máximo de cuentas |
| POST | `/cuentas-garmin/vincular` | `alias`, `garmin_email`, `garmin_password` | Si no pide MFA: 303 → `/cuentas-garmin?vinculada=1`, o `?recuperada=1&cuenta=<id>` si recupera una cuenta (R7); el listado muestra "Se ha recuperado la cuenta «alias» con sus datos." buscando el alias solo entre las cuentas propias. Si pide MFA: 200 con la página del código (`attempt_id` oculto y tiempo restante) | 422: alias no válido o en uso, error de Garmin, ya vinculada por el propio usuario (indica el alias) o por otro (sin decir quién); 409: máximo de cuentas; 429: límite de intentos; 303 → aviso si no lo ha aceptado |
| POST | `/cuentas-garmin/mfa` | `attempt_id`, `mfa_code` | 303 → `/cuentas-garmin?vinculada=1`, `?recuperada=1&cuenta=<id>` o `?reautenticada=1`, según el propósito | 422: código incorrecto (el intento sigue vivo y se vuelve a mostrar la página del código); 410 "El intento ha caducado; vuelve a empezar." si no existe, ha caducado o es de otro usuario |
| POST | `/cuentas-garmin/mfa/cancelar` | `attempt_id` | 303 → `/cuentas-garmin`. Descarta el intento | — |
| GET | `/cuentas-garmin/{account_id}/reautenticar` | — | 200, formulario (correo y contraseña). Si no ha aceptado el aviso vigente: 303 → aviso con `next` | 404; 409 si está `unlinked` o `deleting` |
| POST | `/cuentas-garmin/{account_id}/reautenticar` | `garmin_email`, `garmin_password` | 303 → `/cuentas-garmin?reautenticada=1`, o 200 con la página del código MFA | 404; 409 (estado o candado); 422 (error de Garmin o identidad distinta, US4-2); 429 |
| POST | `/cuentas-garmin/{account_id}/comprobar` | — | 200, fragmento HTMX de la fila con el estado y la fecha actualizados y un mensaje ("Funciona correctamente", o el de R10). Si la cuenta se desvinculó mientras tanto: "La cuenta ha cambiado mientras se comprobaba; recarga la página." (R6) | 404; 409 (estado, candado o "Ya se ha comprobado hace menos de un minuto.") |
| GET | `/cuentas-garmin/{account_id}/desvincular` | — | 200. Explica "conservar" y "borrar", y avisa de que, si conserva los datos, los entrenadores con consentimiento seguirán viéndolos (FR-023) | 404; 409 si está `unlinked` o `deleting` |
| POST | `/cuentas-garmin/{account_id}/desvincular` | `mode=keep\|delete`, `confirmation` (escribir el alias) | 303 → `/cuentas-garmin?desvinculada=1` o `?borrada=1` | 404; 409 (estado o candado, R6); 422 si falta `mode` o la confirmación no coincide con el alias (sin distinguir mayúsculas) |
| GET | `/cuentas-garmin/{account_id}/borrar-datos` | — | 200. Confirmación del borrado de una cuenta `unlinked` | 404; 409 si no está `unlinked` |
| POST | `/cuentas-garmin/{account_id}/borrar-datos` | `confirmation` (alias) | 303 → `/cuentas-garmin?borrada=1` | 404; 409 (estado o candado); 422 |
| POST | `/cuentas-garmin/{account_id}/reintentar-borrado` | — | 303 → `/cuentas-garmin?borrada=1` | 404; 409 si no está `deleting`; 500 controlado: la página muestra "No se ha podido completar el borrado; inténtalo de nuevo." y la cuenta sigue en `deleting` |

**Notas**
- `POST /cuentas-garmin/vincular` y `POST /cuentas-garmin/{id}/reautenticar` (con su paso MFA)
  exigen haber aceptado el aviso vigente (FR-011, FR-012, SC-006). La comprobación se repite en
  el POST aunque el GET ya haya redirigido.
- `POST /cuentas-garmin/mfa` comprueba que `attempt_id` sea del usuario de la sesión. Si no lo
  es, responde lo mismo que un intento caducado.

## Cambios en rutas de 001

| Ruta | Cambio |
|------|--------|
| `GET /` | Muestra hasta dos avisos (R13, FR-016a y FR-012):<br>(1) "Estas cuentas necesitan atención: «alias» (Requiere reautenticación)…", con un enlace a cada acción;<br>(2) "Hay una versión nueva del aviso de datos", con un enlace a `/cuentas-garmin/aviso`.<br>Los administradores no ven ninguno |
| `base.html` | Enlace "Mis cuentas Garmin" en el menú, solo para `role='user'` |
| `GET /cuenta/exportar` | Añade las secciones `garmin_accounts` y `data_notice_acceptances` (FR-030) |
| `POST /cuenta/eliminar` y borrado por el administrador | El paso `garmin_accounts` borra las cuentas Garmin del usuario (FR-029) |

## Etiquetas de estado en la interfaz

| `status` | Etiqueta | Acciones |
|----------|----------|----------|
| `valid` | Válida | Comprobar, Reautenticar, Desvincular |
| `reauth_required` | Requiere reautenticación | Reautenticar (destacada), Comprobar, Desvincular |
| `error` | Error: <motivo de R10> | Reautenticar (destacada), Comprobar, Desvincular |
| `unlinked` | Desvinculada (datos conservados) | Borrar datos, y vincular de nuevo desde "Vincular cuenta" |
| `deleting` | Borrando datos… (no se pudo completar) | Reintentar |
