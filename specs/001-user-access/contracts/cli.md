# Contrato CLI: `garmin-hub` (feature 001)

- La aplicación Typer está en `garmin_hub.cli.main:app` y se publica como script `garmin-hub` en
  `pyproject.toml`.
- Todos los comandos cargan `Settings` y `SecretProvider` al empezar.
- Los mensajes para el operador están en español.

## Códigos de salida comunes

| Código | Significado |
|--------|-------------|
| 0 | Éxito |
| 1 | Error de validación o de negocio (por ejemplo, correo ya registrado o contraseña no válida) |
| 2 | Falta configuración o hay secretos obligatorios ausentes o no válidos (FR-001) |
| 3 | No se puede conectar con la base de datos o el esquema no está actualizado |

Cuando faltan secretos, el mensaje a stderr es este (nunca incluye valores):

```
Error: faltan secretos obligatorios: GARMIN_HUB_DB_URL, GARMIN_HUB_SESSION_SECRET.
Defínelos como variables de entorno (ver .env.example).
```

## `garmin-hub db upgrade [--revision TEXT]`

- Aplica las migraciones de Alembic hasta `--revision` (`head` por defecto) en el schema
  `GARMIN_HUB_DB_SCHEMA`.
- Configura Alembic de forma programática (no depende del directorio actual ni de `alembic.ini`).
- Es idempotente: ejecutarlo dos veces seguidas deja el mismo estado y devuelve 0.
- stdout: `Base de datos actualizada a la revisión <rev>.`

## `garmin-hub admin create --email TEXT --name TEXT`

- Pide la contraseña con `typer.prompt(hide_input=True, confirmation_prompt=True)`, que funciona
  en PowerShell y en bash. **No existe** ninguna opción `--password`.
- Valida el correo (formato y que no exista), el nombre (de 1 a 100 caracteres) y la política de
  contraseñas (FR-015 y FR-016). Si algo falla, devuelve 1 con el motivo y no crea nada.
- Si el esquema no está en `head`, devuelve 3 y sugiere `garmin-hub db upgrade`.
- Si todo va bien, inserta `app_user` con `role='admin'` y `status='active'`, y registra la
  auditoría `admin.created` con `actor_user_id=NULL` e `ip=NULL`.
- stdout: `Administrador creado: <user_id>`. No imprime el correo ni la contraseña.

## `garmin-hub web serve [--host TEXT] [--port INT] [--reload]`

- Valores por defecto: `--host 127.0.0.1` y `--port 8000`.
- Lanza uvicorn con `proxy_headers=True` y `forwarded_allow_ips=GARMIN_HUB_TRUSTED_PROXIES`
  (research R11), y con el log de acceso filtrado (R14).
- Antes de escuchar comprueba los secretos (código 2), la conexión a la base de datos y la revisión
  del esquema (código 3).
- `--reload` solo está permitido si `GARMIN_HUB_ENV=dev`.

## Fuera de esta feature

`key generate`, `worker run`, `rebuild`, `backfill` y `health show` se definirán en las features
que los introduzcan.
