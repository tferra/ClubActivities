# Contrato: interfaz `GarminClient` (feature 002)

Es la interfaz propia de acceso a Garmin (constitución III y VII). Está en
`src/garmin_hub/garmin/client.py`. Ningún otro módulo importa `garminconnect` ni `curl_cffi`
(research R1).

## Tipos

```python
class GarminTokens:            # bytes opacos (JSON de Client.dumps()); repr enmascarado
    value: bytes

class GarminIdentity:
    profile_id: int            # nunca en logs ni en repr

class LoginSucceeded:
    tokens: GarminTokens
    identity: GarminIdentity

class MfaPending:              # se guarda tal cual en PendingLoginRegistry (R3)
    handle: object             # opaco; solo lo entiende la implementación que lo creó

class VerifyResult:
    identity: GarminIdentity
    renewed_tokens: GarminTokens | None   # no es None si la librería renovó el acceso
```

## Operaciones

| Operación | Comportamiento | Errores |
|-----------|----------------|---------|
| `start_login(email: str, password: str) -> LoginSucceeded \| MfaPending` | Hace un login nuevo, con el control de estrategias, pausas, tiempo máximo y reintentos configurables de R11. Ni la contraseña ni el correo se conservan en el resultado ni en el objeto | `InvalidCredentials`, `RateLimited`, `TemporarilyBlocked`, `GarminUnavailable`, `GarminProtocolError` |
| `complete_mfa(pending: MfaPending, code: str) -> LoginSucceeded` | Completa el login. Con un código incorrecto, `pending` sigue siendo válido para otro intento | `InvalidMfaCode`, `RateLimited`, `TemporarilyBlocked`, `GarminUnavailable`, `GarminProtocolError` |
| `discard(pending: MfaPending) -> None` | Libera la sesión HTTP del intento. Es idempotente | — |
| `verify(tokens: GarminTokens) -> VerifyResult` | Hace una petición ligera (`socialProfile`), sin descargar datos. Aplica el backoff de R11 | `TokenRejected`, `RateLimited`, `GarminUnavailable`, `GarminProtocolError` |

Todos los errores heredan de `GarminError`. Su `str()` es un texto fijo en inglés, sin contenido
de Garmin. El mapeo a mensajes y estados está en research R10.

## `GarminConnectClient` (real)

- Usa `garminconnect.client.Client`, con una instancia nueva por login y por verificación.
- `start_login` recorre las estrategias una a una (research R11):
  - en cada paso llama a `login(email, password, return_on_mfa=True)` con `skip_strategies` igual
    al resto;
  - entre estrategias hace una pausa con jitter;
  - se detiene ante 429, 403, unas credenciales rechazadas, una petición de MFA o al agotar los
    45 s;
  - reintenta el login completo hasta `login_max_retries` veces, 0 por defecto.

  Cuando una estrategia responde:
  - si devuelve `("needs_mfa", None)`, el resultado es `MfaPending(handle=client)`;
  - si no, obtiene `profileId` con `connectapi("/userprofile-service/socialProfile")` y
    `dumps()`, y comprueba que haya `di_refresh_token` (R5).
- `complete_mfa` llama a `client.resume_login(None, code)`. La librería ignora el primer argumento
  (R3).
- `verify` hace `loads(tokens)` y `connectapi(...socialProfile)`, y compara `dumps()` antes y
  después para detectar si el acceso se ha renovado.
- **Mapeo de excepciones**:
  - `GarminConnectAuthenticationError` → `InvalidCredentials` (en el login) o `InvalidMfaCode`
    (en el MFA);
  - `GarminConnectTooManyRequestsError` → `RateLimited`;
  - en el login, un 403 de SSO (`exc.response.status_code == 403` o el patrón `\b403\b` en el
    texto, que solo se usa para clasificar) → `TemporarilyBlocked`;
  - `GarminConnectConnectionError` con una respuesta 401 o 403 → `TokenRejected`;
  - `GarminConnectConnectionError` con 5xx o un error de red → `GarminUnavailable`;
  - cualquier otra → `GarminProtocolError`.

## `FakeGarminClient` (tests y `GARMIN_HUB_GARMIN_CLIENT=fake`)

Es determinista, no usa red y su comportamiento depende del correo:

| Correo | Comportamiento de `start_login` |
|--------|---------------------------------|
| `ok+<n>@example.test` | `LoginSucceeded` con `profile_id = <n>` y la contraseña `correcta` |
| `mfa+<n>@example.test` | `MfaPending`; `complete_mfa` acepta el código `123456` |
| `ratelimit@example.test` | `RateLimited` |
| `blocked@example.test` | `TemporarilyBlocked` |
| `down@example.test` | `GarminUnavailable` |
| cualquier otro correo, o una contraseña distinta de `correcta` | `InvalidCredentials` |

- **`verify`**: por defecto devuelve la identidad, salvo si `profile_id >= 9000`, en cuyo caso
  lanza `TokenRejected` (para la demo de "Requiere reautenticación"). Los tests pueden programar el resultado de un `profile_id` concreto (válido,
  `TokenRejected`, transitorio o con renovación) con `fake.script_verify(profile_id, outcome)`.
- **Registro de llamadas**: guarda las llamadas en `fake.calls`, para comprobar que no se ha
  contactado con Garmin (por ejemplo, con el límite de intentos superado).
- **Ayudas para tests**: `fake.password` cambia la contraseña aceptada (para usar una
  contraseña centinela en SC-002), `fake.token_extra` añade un texto a los accesos que devuelve, y
  `fake.hooks[<operación>]` ejecuta una función una sola vez justo antes de devolver
  `start_login`, `complete_mfa` o `verify` (para probar carreras con una desvinculación).
- Los valores `correcta` y `123456` son de prueba y solo existen en este cliente falso.
