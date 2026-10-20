# garmin-hub

Aplicación web multiusuario para descargar y visualizar los datos de cuentas de Garmin Connect
(actividades, salud diaria) y compartirlos con entrenadores de un club, siempre con el
consentimiento explícito del atleta.

La feature `001-user-access` incluye la base del proyecto y la gestión de usuarios y acceso:

- alta solo por invitación ligada a un correo;
- inicio y cierre de sesión con límites de intentos;
- perfil, cambio de contraseña y exportación de los datos propios;
- administración de usuarios e invitaciones;
- borrado del propio usuario;
- restablecimiento de contraseña con un código que genera el administrador.

La feature `002-garmin-account-linking` añade la vinculación de cuentas Garmin Connect desde
"Mis cuentas Garmin":

- vincular una o varias cuentas propias con un alias, el correo, la contraseña y, si Garmin lo
  pide, el código de verificación (MFA), tras aceptar el aviso de datos;
- ver su estado, comprobar que el acceso sigue funcionando y reautenticarlas;
- desvincularlas conservando o borrando sus datos.

La contraseña y el correo de Garmin no se guardan: solo el acceso que concede Garmin, cifrado.
La descarga de datos, los clubes y los entrenadores llegan en features posteriores.

## Requisitos

- Python 3.12 o superior y [uv](https://docs.astral.sh/uv/).
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/microsoft-odbc-driver-for-sql-server).
- Una base de datos SQL Server (la aporta el propietario). Para los tests de integración, una
  base desechable.
- Para usar la web en desarrollo, Chrome, Edge o Firefox: las cookies son siempre `Secure` y
  esos navegadores las aceptan en `http://localhost`.

## Instalación

bash (Linux, WSL, macOS):

```bash
uv sync
cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

PowerShell (Windows):

```powershell
uv sync
Copy-Item .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Pega el valor generado en `GARMIN_HUB_SESSION_SECRET` y rellena `GARMIN_HUB_DB_URL` en `.env`.
Genera también la clave de cifrado de los accesos a Garmin y ponla en `GARMIN_HUB_MASTER_KEYS`
con la versión 1 (`1:<clave>`):

```bash
uv run garmin-hub key generate
```

## Configuración

Todas las variables están documentadas en [`.env.example`](.env.example).

- Los **secretos** (`GARMIN_HUB_DB_URL`, `GARMIN_HUB_SESSION_SECRET`, `GARMIN_HUB_MASTER_KEYS`)
  solo llegan por variables de entorno a través de `SecretProvider`; nunca se guardan en el
  repositorio.
- `.env` solo se lee si `GARMIN_HUB_ENV=dev`, y las variables del entorno real tienen prioridad.
- `GARMIN_HUB_PUBLIC_URL` es obligatoria (`http://localhost:8000` en desarrollo). Abre la web
  exactamente en esa URL.
- Si falta un secreto o la configuración obligatoria, los comandos terminan con el código 2 y
  nombran lo que falta, sin mostrar ningún valor.

## Comandos

```bash
uv run garmin-hub db upgrade                                   # crea o actualiza el esquema (idempotente)
uv run garmin-hub admin create --email admin@club.test --name Admin   # pide la contraseña sin eco
uv run garmin-hub web serve                                    # http://localhost:8000
uv run garmin-hub key generate                                 # clave nueva para GARMIN_HUB_MASTER_KEYS
uv run garmin-hub key reencrypt                                # recifra los accesos con la clave vigente
```

| Código de salida | Significado |
|------------------|-------------|
| 0 | Éxito |
| 1 | Error de validación (correo ya registrado, contraseña no válida…) |
| 2 | Faltan secretos o configuración obligatoria |
| 3 | No hay conexión con la base de datos o el esquema no está actualizado |

Los administradores solo se crean con `admin create`; ninguna acción de la web otorga ese rol.
Los administradores no tienen acceso a las cuentas Garmin de los usuarios.

## Cuentas Garmin

- **Claves de cifrado**: `GARMIN_HUB_MASTER_KEYS` tiene el formato
  `<versión>:<clave>[,<versión>:<clave>...]`, y la clave vigente es la de versión más alta. Para
  rotarla:
  1. genera una clave con `key generate` y añádela con una versión mayor;
  2. reinicia la aplicación;
  3. ejecuta `key reencrypt` (sale con 1 si queda algún acceso con una versión que ya no está
     configurada);
  4. retira la versión antigua.
- **Cliente falso para desarrollo**: con `GARMIN_HUB_ENV=dev` y `GARMIN_HUB_GARMIN_CLIENT=fake`,
  la web no contacta con Garmin. Los correos `ok+<n>@example.test` vinculan la cuenta `<n>` con
  la contraseña `correcta`; los `mfa+<n>@example.test` piden el código `123456`;
  `ratelimit@`, `blocked@` y `down@example.test` simulan errores de Garmin; y las cuentas con
  `<n>` ≥ 9000 dejan de funcionar al comprobarlas. En `prod`, `fake` se rechaza al arrancar.
- **Un solo proceso web**: el intento de login que espera el código MFA vive en la memoria del
  proceso durante 5 minutos como máximo (constitución VII). La web debe ejecutarse con un único
  proceso (`web serve` ya lo hace) o con afinidad de sesión; si el proceso se reinicia, el
  usuario solo tiene que volver a empezar el login.
- **Respeto a Garmin**: una sola petición en curso por cuenta, una comprobación por minuto,
  5 logins fallidos cada 15 minutos por usuario, pausas con jitter entre las estrategias de
  login, corte ante el primer 429 y un tiempo máximo de 45 s por login. Los límites son
  configurables (`GARMIN_HUB_GARMIN_*` en `.env.example`).

## Calidad

```bash
uv run ruff check
uv run ruff format --check
uv run pytest                     # unitarios: sin red ni base de datos
```

Tests de integración contra SQL Server desechable (cada ejecución crea y borra un schema
`gh_t_<hex>`):

```bash
GARMIN_HUB_TEST_DB_URL="mssql+pyodbc://..." uv run pytest -m integration
```

```powershell
$env:GARMIN_HUB_TEST_DB_URL="mssql+pyodbc://..."; uv run pytest -m integration
```

Con `GARMIN_HUB_TEST_DB_URL=sqlite://` se puede hacer una comprobación rápida local; los tests
que dependen de SQL Server (migraciones, trigger de auditoría, concurrencia) se omiten. La
validación de referencia es siempre contra SQL Server.

Prueba opcional contra Garmin real con una cuenta propia (marca `live`, nunca se ejecuta por
defecto). Las credenciales solo se ponen en la sesión de terminal, nunca en `.env`:

```bash
GARMIN_HUB_LIVE_GARMIN_EMAIL=... GARMIN_HUB_LIVE_GARMIN_PASSWORD=... uv run pytest -m live -s
```

```powershell
$env:GARMIN_HUB_LIVE_GARMIN_EMAIL="..."; $env:GARMIN_HUB_LIVE_GARMIN_PASSWORD="..."; uv run pytest -m live -s
```

## Cómo se desarrolla

El proyecto sigue [Spec Kit](https://github.com/github/spec-kit) y su
[constitución](.specify/memory/constitution.md): cada feature pasa por `/speckit-specify` →
`/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` →
`/speckit-implement`. La documentación de cada feature está en `specs/`:
[`specs/001-user-access/`](specs/001-user-access/) y
[`specs/002-garmin-account-linking/`](specs/002-garmin-account-linking/), cada una con su guía de
validación en `quickstart.md`.

La interfaz y la documentación están en español; el código, los nombres de tablas y columnas,
los logs y los commits, en inglés.
