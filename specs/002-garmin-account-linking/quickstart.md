# Quickstart: Vinculación y gestión de cuentas Garmin (002)

Guía para comprobar de principio a fin que la feature funciona. Los detalles están en
[data-model.md](data-model.md), [contracts/http.md](contracts/http.md),
[contracts/cli.md](contracts/cli.md), [contracts/audit-events.md](contracts/audit-events.md) y
[contracts/garmin-client.md](contracts/garmin-client.md).

## Requisitos previos

- La feature 001 configurada según `specs/001-user-access/quickstart.md`, con la base, `.env`, un
  administrador y un usuario normal (por ejemplo `ana@club.test`).
- Para la validación manual se usa el cliente falso, sin red ni cuentas reales. La prueba con
  Garmin real va aparte y es opcional (al final de esta guía).

## Configuración

```bash
uv sync
uv run garmin-hub key generate
# <clave>
# Añádela a GARMIN_HUB_MASTER_KEYS con una versión mayor que la actual, por ejemplo 2:<clave>
```

Añade a `.env`:

```
GARMIN_HUB_MASTER_KEYS=1:<clave generada>
GARMIN_HUB_GARMIN_CLIENT=fake
```

Después:

```bash
uv run garmin-hub db upgrade          # → Base de datos actualizada a la revisión 0002_garmin_accounts.
uv run garmin-hub web serve
```

## Validación por escenarios

Hay que entrar como `ana@club.test` salvo que se indique otra cosa. Los correos y códigos de
Garmin de prueba están en contracts/garmin-client.md.

| # | Paso | Resultado esperado |
|---|------|--------------------|
| 0 | Quitar `GARMIN_HUB_MASTER_KEYS` y ejecutar `uv run garmin-hub web serve` | Código 2 y `Error: faltan secretos obligatorios: GARMIN_HUB_MASTER_KEYS.`, sin ningún valor (FR-027). Con `GARMIN_HUB_MASTER_KEYS=basura`: código 2 y `Error: secretos no válidos: GARMIN_HUB_MASTER_KEYS (formato <versión>:<clave>[,<versión>:<clave>...] con claves Fernet).` Con `GARMIN_HUB_ENV=prod` y `GARMIN_HUB_GARMIN_CLIENT=fake`: código 2 y `Error: falta configuración obligatoria: GARMIN_HUB_GARMIN_CLIENT (fake solo en dev o test).` Volver a dejarlo como estaba |
| 1 | Menú → "Mis cuentas Garmin" | Listado vacío con "Todavía no has vinculado ninguna cuenta Garmin." y el enlace "Vincular una cuenta Garmin" (US2-3) |
| 2 | "Vincular una cuenta Garmin" | Redirige al aviso de datos. Sin marcar la casilla: "Marca la casilla «He leído y acepto» para continuar."; al aceptarlo vuelve al formulario (US6-1, US6-2) |
| 3 | Vincular con alias `Principal`, correo `ok+1001@example.test` y contraseña `correcta` | Vuelve al listado con "Cuenta Garmin vinculada."; `Principal` aparece como "Válida", con el último login de ahora y la última sincronización y la última comprobación "Nunca" (US1-1) |
| 4 | Vincular `Bici`, `mfa+1002@example.test` / `correcta`; en la página del código (con "Tiempo restante: 5:00 minutos"), escribir `000000` y después `123456` | Primero muestra "El código de verificación no es correcto." y deja reintentar; con `123456` vincula la cuenta (US1-2, US1-4) |
| 5 | Repetir el paso 4 y esperar más de 5 minutos antes de enviar el código | "El intento ha caducado; vuelve a empezar." (US1-3) |
| 6 | Vincular `Otra`, `ok+1001@example.test` / `correcta` | "Ya tienes vinculada esta cuenta Garmin como «Principal»." (US1-7) |
| 7 | Vincular con contraseña `mala` | "Garmin no acepta ese correo o contraseña." y no se crea nada (US1-5). Tras 5 fallos en 15 minutos, el sexto intento (aunque sea correcto) da "Has hecho demasiados intentos con Garmin; espera unos minutos." sin contactar con Garmin (FR-010). Esperar 15 minutos antes de seguir |
| 8 | Vincular con `down@example.test`, `ratelimit@example.test` y `blocked@example.test` | "No se ha podido conectar con Garmin; inténtalo más tarde.", "Garmin está limitando las peticiones; inténtalo dentro de un rato." y "Garmin ha bloqueado temporalmente el inicio de sesión; inténtalo más tarde." (FR-026); no se crea nada |
| 9 | "Comprobar" en `Principal` y volver a pulsarlo enseguida | La fila se actualiza sin recargar con "Funciona correctamente." y la fecha de comprobación. La segunda vez: "Ya se ha comprobado hace menos de un minuto." (US7-1, US7-4) |
| 10 | Con otro usuario normal (`luis@club.test`), vincular `ok+1001@example.test` | "Esta cuenta Garmin ya está vinculada a otro usuario de garmin-hub.", sin decir quién la tiene (US1-6). Al abrir `/cuentas-garmin/<id de Principal>/desvincular`: "No encontrado", igual que con un UUID inventado o con `/cuentas-garmin/abc/desvincular` (US3-2) |
| 11 | Entrar como administrador y abrir `/cuentas-garmin` | 404; el menú no muestra "Mis cuentas Garmin" (US3-3, US1-8) |
| 12 | Como Ana: desvincular `Bici` con "conservar datos" escribiendo el alias | La pantalla avisa de que los entrenadores con consentimiento seguirán viendo los datos. `Bici` queda "Desvinculada (datos conservados)" (US5-1, US5-3) |
| 13 | Vincular de nuevo `mfa+1002@example.test` con otro alias (código `123456`) | "Se ha recuperado la cuenta «Bici» con sus datos."; mismo identificador interno y alias original (US5-4) |
| 14 | Desvincular `Principal` con "borrar datos" | "Se han borrado la cuenta Garmin y sus datos." y desaparece del listado. Tras ello, Luis puede vincular `ok+1001@example.test` (US5-2, US5-7) |
| 15 | Exportar desde `/cuenta/exportar` | El JSON incluye `garmin_accounts` (alias, estado y fechas) y `data_notice_acceptances`, sin accesos, correo ni `profileId` (FR-030) |
| 16 | Vincular `Caduca` con `ok+9001@example.test` / `correcta` y pulsar "Comprobar" | "Garmin ya no acepta el acceso guardado; vuelve a autenticar la cuenta." y `Caduca` pasa a "Requiere reautenticación"; la página de inicio muestra "Estas cuentas necesitan atención:" con «Caduca» (Requiere reautenticación) y un enlace. Reautenticar con el mismo correo y `correcta`: vuelve a "Válida" con el mismo identificador y el aviso desaparece (US7-2, US4-1, US2-5, FR-016a). Reautenticar con `ok+1003@example.test`: "Esas credenciales son de otra cuenta Garmin distinta de «Caduca»." (US4-2) |
| 17 | `uv run garmin-hub key generate`, añadir `2:<clave nueva>` a `GARMIN_HUB_MASTER_KEYS` (dejando la 1), reiniciar y ejecutar `uv run garmin-hub key reencrypt` | `Accesos recifrados: <n>. Pendientes con versiones no configuradas: 0.` y código 0; repetirlo da `Accesos recifrados: 0.` Las cuentas siguen "Válidas". Después se puede retirar la versión 1; si queda algún acceso con una versión no configurada, el comando lo cuenta como pendiente y sale con 1 |

## Tests automáticos

```bash
uv run ruff check
uv run ruff format --check
uv run pytest                                  # unitarios
GARMIN_HUB_TEST_DB_URL=... uv run pytest -m integration   # incluye la migración 0002 arriba y abajo y SC-002
```

Con `GARMIN_HUB_TEST_DB_URL=sqlite://` se omiten los tests `mssql`: la migración 0002 (subida,
bajada, CHECK e índices filtrados), la concurrencia de la vinculación y los de 001 que dependen
de SQL Server.

En PowerShell: `$env:GARMIN_HUB_TEST_DB_URL="..."; uv run pytest -m integration`.

## Prueba con Garmin real (opcional, `live`)

Usa una cuenta Garmin propia. Las credenciales se definen solo en la sesión de terminal y nunca
se guardan en `.env` ni en el repositorio.

```bash
export GARMIN_HUB_LIVE_GARMIN_EMAIL=...       # PowerShell: $env:GARMIN_HUB_LIVE_GARMIN_EMAIL="..."
export GARMIN_HUB_LIVE_GARMIN_PASSWORD=...
uv run pytest -m live tests/live -s            # -s para escribir el código MFA si se pide
```

Resultado esperado:
- el login y `verify` funcionan;
- el test confirma que el JSON de los accesos tiene un token de renovación;
- los logs capturados no contienen el correo ni la contraseña.

Repetirlo cuando se actualice `garminconnect` (research R1).
