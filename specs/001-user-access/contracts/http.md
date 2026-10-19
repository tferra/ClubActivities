# Contrato HTTP: web de garmin-hub (feature 001)

## Reglas generales

- Las vistas son HTML renderizado en el servidor (Jinja2), con textos en español.
- Las acciones de las listas de administración usan HTMX, que devuelve fragmentos HTML.
- **CSRF**:
  - Todo POST exige un token válido (research R9): el campo `csrf_token` o la cabecera
    `X-CSRF-Token`. Lo comprueba la dependencia `require_csrf`, aplicada a nivel de router, y la
    ruta sigue recibiendo todos los campos del formulario.
  - Si `Origin` está presente, debe coincidir con `GARMIN_HUB_PUBLIC_URL`.
  - Si falla, la respuesta es `403` con la página "La sesión del formulario ha caducado; recarga e
    inténtalo de nuevo".
- **Autenticación**: una ruta autenticada sin sesión válida responde `303 → /login`. Si es una
  petición HTMX, responde `200` con la cabecera `HX-Redirect: /login`.
- **Administración**: las rutas `/admin/**` responden `404` a quien no es administrador, para no
  revelar que existen.
- **Cabeceras**: todas las respuestas llevan las cabeceras de seguridad de R12. Las autenticadas
  añaden `Cache-Control: no-store`.
- **Errores de validación**: se vuelve a mostrar el formulario con estado `422`, el mensaje en
  español y los campos no sensibles conservados. Las contraseñas nunca se devuelven.
- **Mensajes genéricos** (FR-008 y FR-032):
  - inicio de sesión: "Correo o contraseña incorrectos.";
  - códigos: "El código no es válido o ha caducado.";
  - bloqueo: el mismo texto que el fallo correspondiente, con estado `200`/`422` igual que un fallo
    normal.

## Rutas públicas

| Método | Ruta | Formulario o parámetros | Éxito | Fallo |
|--------|------|-------------------------|-------|-------|
| GET | `/login` | — | 200, formulario | — |
| POST | `/login` | `email`, `password`, `csrf_token` | 303 → `/`; crea una sesión nueva y pone la cookie | 422, mensaje genérico |
| POST | `/logout` | `csrf_token` | 303 → `/login`; borra la sesión y la cookie | — |
| GET | `/alta` | — | 200, paso 1 (código) | — |
| POST | `/alta/codigo` | `code`, `csrf_token` | 200, paso 2 con el correo de la invitación en solo lectura y el código en un campo oculto | 422, mensaje genérico de código |
| POST | `/alta` | `code`, `display_name`, `password`, `password_confirm`, `csrf_token` | 303 → `/`, con sesión iniciada | 422; el código no se consume (FR-014). Un campo `email` presente y distinto del de la invitación se rechaza con el mensaje genérico |
| GET | `/restablecer` | — | 200, formulario | — |
| POST | `/restablecer` | `email`, `code`, `password`, `password_confirm`, `csrf_token` | 303 → `/login?restablecida=1` | 422, mensaje genérico de código |
| GET | `/healthz` | — | 200 `ok`, sin acceso a la base de datos | — |

`POST /login`, `POST /alta/codigo`, `POST /alta` y `POST /restablecer` aplican el límite de
intentos (R10). Son `async def` y esperan el retardo de R10 sin ocupar un hilo del servidor.

## Rutas autenticadas

| Método | Ruta | Formulario | Éxito | Fallo |
|--------|------|------------|-------|-------|
| GET | `/` | — | 200, página de inicio (marcador de posición para features posteriores) | — |
| GET | `/cuenta` | — | 200, perfil (nombre y correo) | — |
| POST | `/cuenta/nombre` | `display_name` | 303 → `/cuenta` | 422 |
| POST | `/cuenta/contrasena` | `current_password`, `password`, `password_confirm` | 303 → `/cuenta`; cierra las demás sesiones | 422. Un `current_password` incorrecto cuenta como intento de tipo `current_password` para el límite del par correo + origen (FR-030); si el par está bloqueado, 422 con el mismo mensaje |
| GET | `/cuenta/exportar` | — | 200, `application/json` con `Content-Disposition: attachment; filename="garmin-hub-export.json"`: `{"format_version": 1, "exported_at", "profile": {...}, "audit_events": [...]}`. Nunca incluye `password_hash` ni datos de otros usuarios (FR-023a) | — |
| GET | `/cuenta/eliminar` | — | 200; explica qué se borra y pide la contraseña y escribir `ELIMINAR` | — |
| POST | `/cuenta/eliminar` | `current_password`, `confirmation` | 303 → `/login?eliminada=1` | 422 sin borrar nada; 409 si es el último administrador activo |

## Rutas de administración

| Método | Ruta | Formulario | Éxito | Fallo |
|--------|------|------------|-------|-------|
| GET | `/admin/usuarios` | — | 200, tabla con nombre, correo, rol, estado, alta y último acceso | — |
| POST | `/admin/usuarios/{user_id}/desactivar` | — | 200, fragmento de la fila actualizada | 409: es el propio usuario o el último administrador |
| POST | `/admin/usuarios/{user_id}/reactivar` | — | 200, fragmento | 409 si no está desactivado |
| POST | `/admin/usuarios/{user_id}/restablecimiento` | — | 200, fragmento con el código **visible una sola vez** | 409 si no está activo |
| GET | `/admin/usuarios/{user_id}/eliminar` | — | 200, confirmación (pide escribir el correo del usuario) | 404 si no existe; 409 si no es un usuario normal desactivado |
| POST | `/admin/usuarios/{user_id}/eliminar` | `confirmation_email` | 303 → `/admin/usuarios` | 422 si el correo no coincide; 409 por las mismas reglas |
| POST | `/admin/usuarios/{user_id}/reintentar-borrado` | — | 200, fragmento | 409 si no está en `pending_deletion` |
| GET | `/admin/invitaciones` | — | 200, tabla con correo, estado efectivo, nota, fechas y quién la usó | — |
| POST | `/admin/invitaciones` | `email`, `note?`, `ttl_days?` (de 1 a 30) | 200, fragmento con el código **visible una sola vez** | 422: correo no válido, ya registrado o con una invitación pendiente |
| POST | `/admin/invitaciones/{invitation_id}/revocar` | — | 200, fragmento | 409 si no está pendiente |

Un `{user_id}` o `{invitation_id}` inexistente devuelve `404`.

## Cookies

| Nombre | Contenido | Atributos |
|---------------------|-----------|-----------|
| `__Host-gh_session` | id de sesión aleatorio | HttpOnly, Secure, SameSite=Lax, Path=/; sin Max-Age (de sesión) |
| `__Host-gh_csrf` | nonce para los formularios anónimos | HttpOnly, Secure, SameSite=Lax, Path=/ |

Los nombres y atributos son los mismos en todos los entornos (constitución IV). En desarrollo,
`http://localhost` funciona con Chrome, Edge y Firefox, que lo tratan como contexto seguro.
