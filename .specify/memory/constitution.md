# garmin-hub Constitution

Aplicación web multiusuario en Python que descarga datos de cuentas Garmin Connect (actividades y
salud diaria), los almacena en SQL Server y los muestra con gráficas. Contempla usuarios con varias
cuentas Garmin, clubes, entrenadores y consentimiento de acceso a datos de salud.

En este documento, DEBE / NO DEBE expresan obligaciones no negociables y DEBERÍA expresa una
recomendación fuerte cuya excepción se justifica por escrito en el plan de la feature.

## Core Principles

### I. Datos crudos primero

- Toda respuesta descargada de Garmin (el JSON de cada endpoint y el fichero `.FIT` original) DEBE
  persistirse sin modificar en la capa cruda antes de cualquier transformación.
- La capa cruda DEBE leerse y escribirse exclusivamente a través de la interfaz `RawStore`
  (implementación actual: sistema de ficheros; prevista: Azure Storage). Ningún módulo accede a
  rutas crudas directamente.
- Cada endpoint consultado DEBE guardarse aunque la interfaz web aún no use sus datos.
- Todas las tablas derivadas de SQL Server DEBEN poder regenerarse íntegramente desde la capa cruda
  sin llamar a Garmin. DEBE existir un comando de reconstrucción y un test que lo verifique.

**Justificación**: Garmin es una fuente externa, no oficial y con límites; lo crudo permite
reprocesar, corregir errores de parseo y añadir funciones sin volver a descargar.

### II. Idempotencia y reanudabilidad

- Ejecutar una misma extracción N veces DEBE producir el mismo estado que ejecutarla una vez
  (sin filas ni ficheros duplicados). Las tablas derivadas usan claves naturales únicas y upsert.
- Toda extracción DEBE poder interrumpirse en cualquier punto y reanudarse desde su último
  checkpoint sin pérdida ni duplicación.
- Las escrituras de ficheros DEBEN ser atómicas (escritura en un fichero temporal y renombrado).
  Las escrituras en base de datos DEBEN ser transaccionales.
- Toda extracción DEBE ejecutarse como un trabajo registrado en `sync_job`, con estado, progreso,
  checkpoint y errores.

**Justificación**: los procesos largos contra una API externa fallan; reintentar debe ser
seguro y observable.

### III. Respeto a Garmin

- Como máximo DEBE haber una petición en curso por `garmin_account_id`, y como máximo un trabajo
  activo por cuenta, garantizado en la base de datos (p. ej., un índice único filtrado).
- Entre peticiones DEBE haber pausas con jitter. Ante respuestas 429 o 5xx DEBE aplicarse backoff
  exponencial con un límite configurable de reintentos; agotado el límite, el trabajo se detiene
  limpiamente guardando su checkpoint.
- Todo acceso a Garmin DEBE pasar por la interfaz propia `GarminClient`. La librería no oficial
  solo se importa dentro de su implementación, de modo que pueda sustituirse.

**Justificación**: evitar bloqueos de cuentas y depender lo menos posible de una librería no
oficial.

### IV. Seguridad

- La contraseña de Garmin NO DEBE persistirse ni escribirse en logs: solo vive en memoria durante
  el login. Ningún esquema ni modelo tiene un campo para ella.
- Los tokens de Garmin DEBEN almacenarse cifrados con Fernet junto con una `key_version` que
  permita rotar la clave.
- Las contraseñas de los usuarios de la aplicación DEBEN guardarse con argon2.
- Las sesiones DEBEN guardarse en el servidor, con una cookie `HttpOnly`, `Secure` y `SameSite`.
- Toda petición que modifique estado DEBE tener protección CSRF.
- El login DEBE limitar los intentos.
- DEBEN enviarse cabeceras de seguridad (CSP, HSTS, X-Content-Type-Options, Referrer-Policy y
  frame-ancestors).
- Los mensajes de error NO DEBEN revelar si un usuario existe.
- Los secretos DEBEN llegar por variables de entorno a través de la interfaz `SecretProvider` y
  NUNCA estar en el código ni en el repositorio.
- Ningún secreto, token ni dato personal DEBE aparecer en logs. Un test DEBE verificar el
  enmascaramiento.

**Justificación**: la aplicación custodia credenciales de terceros y datos de salud.

### V. Privacidad y consentimiento

- Las pulsaciones, el sueño y la HRV son datos de salud y DEBEN tratarse con mínimo privilegio.
- El propietario ve sus propios datos. Un entrenador solo ve los datos de un atleta si este le ha
  dado un consentimiento explícito, por entrenador y por categoría (`activities`, `route`,
  `health`). La revocación DEBE surtir efecto en la siguiente petición, sin cachés que la
  retrasen.
- El administrador gestiona usuarios, clubes y solicitudes, pero NO DEBE poder acceder a datos de
  entrenamiento ni de salud de los atletas a través de la interfaz.
- Cada alta, vinculación de una cuenta Garmin, concesión o revocación de consentimiento y cada
  consulta de un entrenador a datos de un atleta DEBE registrarse en una tabla de auditoría de
  solo inserción (el rol de la aplicación no tiene permisos UPDATE ni DELETE sobre ella).
- Todo usuario DEBE poder exportar sus datos y borrar una cuenta Garmin o su propio usuario. El
  borrado elimina los datos en la base de datos y los ficheros crudos asociados.

**Justificación**: los datos de salud exigen consentimiento granular, trazabilidad y derecho de
supresión (RGPD).

### VI. Autorización centralizada y denegación por defecto

- DEBE existir una única política de acceso a datos de atleta:
  `can_view(principal, garmin_account, category)`. Ninguna ruta, plantilla ni consulta accede a
  datos de atleta sin pasar por ella.
- Ante cualquier caso no contemplado, la política DEBE denegar.
- DEBE haber tests que cubran cada combinación de rol, pertenencia a club, consentimiento
  (concedido, inexistente o revocado) y categoría.

**Justificación**: una única política verificable evita fugas por rutas olvidadas.

### VII. Portabilidad

- Los procesos web y worker DEBEN ser sin estado; el estado vive en SQL Server y en `RawStore`.
- Toda la configuración DEBE llegar por variables de entorno (12 factores).
- La aplicación DEBE poder ejecutarse en imágenes Docker.
- Las interfaces `SecretProvider`, `RawStore` y `GarminClient` son los puntos de sustitución para
  migrar a Azure sin reescribir la lógica de negocio.

**Justificación**: el destino previsto es Azure; la migración solo debe cambiar las
implementaciones de esas interfaces.

### VIII. Multiplataforma de desarrollo

- El proyecto DEBE poder desarrollarse, probarse y ejecutarse en Windows (PowerShell) y en
  Linux/WSL (bash).
- Las rutas DEBEN manejarse con `pathlib`; no se concatenan cadenas de ruta.
- No DEBE haber dependencias de shell: las tareas se escriben en Python o como comandos `uv run`.
- El entorno y las dependencias DEBEN gestionarse con `uv`.

**Justificación**: el equipo trabaja en ambos sistemas.

### IX. Calidad verificable

- Python 3.12 o superior. Todo código público DEBE tener anotaciones de tipo.
- `ruff` (lint y formato) y `pytest` son obligatorios.
- El esquema DEBE gestionarse con migraciones de Alembic desde el primer día; ningún cambio de
  esquema se hace fuera de una migración.
- Los tests unitarios NO DEBEN usar red ni cuentas reales; usan fixtures sintéticas.
- Los tests de integración usan una base SQL Server desechable y se marcan `integration`.
- Las pruebas contra Garmin real se marcan `live` y quedan excluidas por defecto.

**Justificación**: la calidad se comprueba con herramientas, no por convención.

### X. Simplicidad

- SQL Server DEBE hacer de base de datos, de cola de trabajos y de almacén de sesiones.
- Están prohibidos Redis, Celery, los microservicios y las SPA.
- Cada dependencia nueva DEBE justificarse en el plan de la feature.
- Se construye solo lo que pide la spec; no se crean abstracciones especulativas más allá de las
  tres interfaces del principio VII.

**Justificación**: menos piezas implica menos fallos y menos coste operativo.

### XI. Modelo de datos y unidades

- Internamente DEBEN usarse unidades SI: metros, segundos, m/s y latidos por minuto.
- La conversión a unidades de presentación DEBE hacerse solo en la capa de vista:
  - ritmo (min/km) para correr y senderismo;
  - velocidad (km/h) para ciclismo;
  - ritmo por 100 m para natación;
  - un conmutador manual permite cambiar entre ritmo y velocidad.
- Las marcas de tiempo DEBEN guardarse en UTC, con la zona horaria del atleta guardada aparte.
- Los identificadores internos (`user_id`, `garmin_account_id`) DEBEN ser estables e independientes
  de alias y correos.

**Justificación**: un único sistema de unidades y de tiempo evita errores de conversión y de
agregación.

### XII. Idioma

- La interfaz de usuario y la documentación DEBEN estar en español.
- El código, los identificadores, los nombres de tablas y columnas y los mensajes de commit DEBEN
  estar en inglés.

**Justificación**: los usuarios son hispanohablantes y el código sigue la convención
internacional.

### XIII. Desarrollo guiado por especificación

- Cada feature DEBE pasar por specify, clarify, plan, tasks, analyze e implement.
- NO DEBE escribirse código sin una tarea asociada en `tasks.md`.
- Una feature solo se da por terminada con todos los tests en verde y `ruff` limpio.

**Justificación**: trazabilidad entre requisito, diseño, tarea y código.

## Restricciones tecnológicas

- **Lenguaje y entorno**: Python 3.12+, gestionado con `uv`.
- **Persistencia**: SQL Server (datos, cola de trabajos `sync_job` y sesiones), con migraciones de
  Alembic. Ficheros crudos a través de `RawStore`.
- **Criptografía**: Fernet (con `key_version`) para los tokens de Garmin y argon2 para las
  contraseñas.
- **Despliegue**: imágenes Docker para web y worker; configuración por variables de entorno a
  través de `SecretProvider`.
- **Interfaz web**: renderizada en el servidor; no se permiten SPA.
- **Prohibido**: Redis, Celery, microservicios, secretos en el repositorio y almacenar la
  contraseña de Garmin.

## Flujo de desarrollo y puertas de calidad

1. Cada feature recorre `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` →
   `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`.
2. El plan DEBE incluir una "Constitution Check" que revise los principios I–XIII. Toda desviación
   se justifica en la tabla de complejidad del plan.
3. Cada cambio de código DEBE poder relacionarse con una tarea de `tasks.md`.
4. Para cerrar una feature, deben pasar en verde:
   - `uv run ruff check`;
   - `uv run ruff format --check`;
   - `uv run pytest` (excluye `live`; `integration` se ejecuta cuando hay una base desechable
     disponible).
5. Los cambios que afecten a autorización o consentimiento DEBEN ampliar la matriz de tests de
   `can_view`.

## Governance

- Esta constitución prevalece sobre cualquier otra práctica o guía del proyecto.
- Toda enmienda DEBE incluir:
  - una justificación escrita;
  - el cambio de versión;
  - la fecha de la última enmienda;
  - el Sync Impact Report de los artefactos afectados.
- La versión sigue semver:
  - **MAJOR** al eliminar o redefinir de forma incompatible un principio;
  - **MINOR** al añadir un principio o sección, o al ampliar una regla de forma sustancial;
  - **PATCH** para aclaraciones y correcciones de redacción.
- La conformidad se revisa en `/speckit-plan` (Constitution Check) y en `/speckit-analyze`. Las
  violaciones de un principio con DEBE son bloqueantes.

**Version**: 1.0.1 | **Ratified**: 2026-10-14 | **Last Amended**: 2026-10-19
