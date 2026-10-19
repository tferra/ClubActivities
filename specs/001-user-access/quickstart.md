# Quickstart: Gestión de usuarios y acceso (001)

Guía para comprobar de principio a fin que la feature funciona. Los detalles están en
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/http.md](contracts/http.md) y [contracts/audit-events.md](contracts/audit-events.md).

## Requisitos previos

- Python 3.12 o superior y [uv](https://docs.astral.sh/uv/).
- Microsoft **ODBC Driver 18 for SQL Server**.
- Acceso a SQL Server:
  - Para trabajar: la base que aporta el propietario.
  - Para los tests de integración: una base desechable. Por ejemplo, un contenedor
    `mcr.microsoft.com/mssql/server:2022-latest` solo para tests; el desarrollo diario no usa
    contenedores.

## Configuración

```bash
uv sync
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"   # → GARMIN_HUB_SESSION_SECRET
```

Valores mínimos en `.env`. El fichero solo se lee si `GARMIN_HUB_ENV=dev` (en el entorno real o
en el propio `.env`), y las variables del entorno real tienen prioridad:

```
GARMIN_HUB_ENV=dev
GARMIN_HUB_DB_URL=mssql+pyodbc://USER:PASS@HOST:1433/DB?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes
GARMIN_HUB_SESSION_SECRET=<valor generado>
GARMIN_HUB_PUBLIC_URL=http://localhost:8000
```

> Rotar `GARMIN_HUB_SESSION_SECRET` cierra todas las sesiones y anula los códigos pendientes.

> **Navegador**: las cookies son siempre `__Host-` y `Secure`, también en desarrollo. Usa Chrome,
> Edge o Firefox, que aceptan cookies `Secure` en `http://localhost`, y abre la aplicación en
> `http://localhost:8000` (la misma URL que `GARMIN_HUB_PUBLIC_URL`; con `127.0.0.1` la
> comprobación de `Origin` rechazaría los formularios).

## Validación por escenarios

| # | Paso | Resultado esperado |
|---|------|--------------------|
| 0 | Sin definir `GARMIN_HUB_SESSION_SECRET` (ni en el entorno ni en `.env`), ejecutar `uv run garmin-hub web serve` | Termina con código 2 y lista el nombre del secreto que falta, nunca un valor (FR-001) |
| 1 | `uv run garmin-hub db upgrade`, dos veces | La primera vez crea el esquema `gh`; la segunda no hace nada. Las dos devuelven 0 |
| 2 | `uv run garmin-hub admin create --email admin@club.test --name Admin` e introducir la contraseña dos veces | Escribe `Administrador creado: <uuid>`; la contraseña no se muestra (US1) |
| 3 | `uv run garmin-hub web serve` y abrir http://localhost:8000 | Redirige a `/login` |
| 4 | Entrar como administrador, ir a Invitaciones y crear una para `ana@club.test` | Muestra el código una sola vez; la invitación aparece como "Pendiente" (US2) |
| 5 | En otra ventana privada, ir a `/alta` y poner el código | El correo `ana@club.test` aparece fijo; tras poner nombre y contraseña se entra en la aplicación (US3; menos de 2 minutos, SC-001) |
| 6 | Repetir `/alta` con el mismo código | "El código no es válido o ha caducado." (SC-002) |
| 7 | Como Ana, fallar 5 veces la contraseña y luego poner la correcta | La sexta vez se rechaza con el mensaje genérico; desde otro origen sí entra (FR-030) |
| 8 | Como Ana, cambiar el nombre y la contraseña, y descargar "Exportar mis datos" | La otra sesión de Ana queda cerrada; el JSON descargado contiene su perfil y sus eventos de auditoría, sin la credencial (US5) |
| 9 | Como administrador, desactivar a Ana con su sesión abierta | La siguiente petición de Ana redirige a `/login` y no puede volver a entrar (SC-003) |
| 10 | Reactivar a Ana, generar un código de restablecimiento y usarlo en `/restablecer` | La contraseña nueva funciona y la antigua no (US8) |
| 11 | Como Ana, `/cuenta/eliminar` con contraseña y `ELIMINAR` | Vuelve a `/login`; el inicio de sesión con su correo se comporta como el de un correo inexistente (US7) |
| 12 | Como administrador, intentar desactivarse a sí mismo | Se rechaza (FR-027) |

## Tests

```bash
uv run ruff check
uv run ruff format --check
uv run pytest                                  # unitarios; sin red ni base de datos
GARMIN_HUB_TEST_DB_URL=... uv run pytest -m integration
```

En PowerShell: `$env:GARMIN_HUB_TEST_DB_URL="..."; uv run pytest -m integration`.

Tests de integración clave:

- **Concurrencia**: dos altas simultáneas con el mismo código dan exactamente un usuario.
- **Inmutabilidad de la auditoría**: un UPDATE o DELETE sobre `audit_event` falla.
- **Borrado completo**: tras borrar a un usuario no queda ninguna fila suya, salvo `audit_event`
  con su UUID y sin datos personales.
- **Sin secretos en claro** (SC-004): se ejecuta un ciclo completo con contraseñas, códigos,
  secreto de sesión, contraseña de la URL de conexión y dirección de red conocidos, y luego se
  recorren todas las columnas de texto y binarias del schema de pruebas y todos los logs
  capturados. Ninguno de esos valores, ni los identificadores de sesión ni los tokens CSRF, ni el
  correo en los logs, aparece en claro.
