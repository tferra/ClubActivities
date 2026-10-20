# Contrato CLI: cambios de la feature 002

Se aplican los códigos de salida y las convenciones de la feature 001
(`specs/001-user-access/contracts/cli.md`).

## Secreto obligatorio nuevo

`load_secrets` exige `GARMIN_HUB_MASTER_KEYS` (research R5) en todos los comandos que ya cargaban
secretos (`db upgrade`, `admin create`, `web serve`) y en `key reencrypt` (FR-027):

```
Error: faltan secretos obligatorios: GARMIN_HUB_MASTER_KEYS.
Defínelos como variables de entorno (ver .env.example).
```

Si el formato o alguna clave no son válidos, el código de salida es `2`:

```
Error: secretos no válidos: GARMIN_HUB_MASTER_KEYS (formato <versión>:<clave>[,<versión>:<clave>...] con claves Fernet).
```

El mensaje nunca incluye valores.

`GARMIN_HUB_GARMIN_CLIENT=fake` con `GARMIN_HUB_ENV=prod` devuelve también `2`:

```
Error: falta configuración obligatoria: GARMIN_HUB_GARMIN_CLIENT (fake solo en dev o test).
```

## `garmin-hub key generate`

- Imprime en stdout una clave Fernet nueva y una línea de ayuda:

  ```
  <clave>
  Añádela a GARMIN_HUB_MASTER_KEYS con una versión mayor que la actual, por ejemplo 2:<clave>
  ```

- No carga secretos ni se conecta a la base de datos, así que funciona antes de la primera
  configuración. Código de salida `0`.

## `garmin-hub key reencrypt`

- Vuelve a cifrar con la clave vigente (la de versión más alta) todas las filas de `garmin_token`
  cuya `key_version` sea menor. Cada fila se procesa en su propia transacción y la operación es
  idempotente.
- stdout: `Accesos recifrados: <n>. Pendientes con versiones no configuradas: <m>.`
- Si una fila usa una versión que ya no está configurada, no se toca y se cuenta en `<m>`. Al
  usarla, esa cuenta pasará a "Error" (R10).
- Códigos de salida: `0` si `<m> = 0`, `1` si `<m> > 0`, `2` por secretos y `3` por la base de
  datos.
- Nunca imprime ni registra accesos ni claves.

## `garmin-hub db upgrade`

Sin cambios de interfaz. Aplica también `0002_garmin_accounts`.
