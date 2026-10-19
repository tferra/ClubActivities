# Feature Specification: Gestión de usuarios y acceso

**Feature Branch**: `001-user-access`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "Gestión de usuarios y acceso a la aplicación web garmin-hub.
Aplicación multiusuario accesible desde internet; cada usuario tiene un identificador propio
independiente de sus cuentas Garmin; alta solo por invitación del administrador. Historias:
primer administrador por línea de comandos; invitaciones de un solo uso con caducidad; alta con
código; inicio y cierre de sesión con caducidad por inactividad; cambio de contraseña y nombre;
administración de usuarios e invitaciones; borrado del propio usuario con todos sus datos;
código de restablecimiento de contraseña generado por el administrador."

## Clarifications

### Session 2026-10-14

- Q: ¿El administrador puede usar también la aplicación como deportista o entrenador, o la cuenta de administrador sirve solo para administrar? → A: Solo para administrar: un usuario administrador no vincula cuentas Garmin ni pertenece a clubes; quien además entrena o compite usa un segundo usuario normal con otro correo.
- Q: ¿Qué pasa con los datos y las descargas de Garmin de un usuario cuando el administrador lo desactiva? → A: Se bloquea el inicio de sesión, se pausan sus descargas de Garmin y los entrenadores dejan de ver sus datos mientras siga desactivado; los datos se conservan y todo se restablece al reactivarlo.
- Q: ¿Puede el administrador borrar a otro usuario con todos sus datos, por ejemplo cuando el interesado lo pide pero ya no puede iniciar sesión? → A: Sí, pero solo a usuarios normales ya desactivados, confirmando con el correo del usuario y dejando constancia en la auditoría.
- Q: Cuando un correo acumula 5 intentos fallidos, ¿se bloquea ese correo desde cualquier lugar o solo desde el origen donde se produjeron los fallos? → A: Se bloquea el par correo + origen 15 minutos tras 5 fallos en 15 minutos; además, un límite global por correo (50 fallos/hora desde cualquier origen) introduce un retardo creciente en lugar de un bloqueo total.
- Q: ¿La invitación va ligada al correo de la persona invitada, de modo que solo pueda darse de alta con ese correo, o vale para cualquier correo? → A: Va ligada: el administrador indica el correo al crear la invitación y el alta solo se acepta con ese correo, que el formulario muestra ya rellenado y sin poder cambiarlo.

### Session 2026-10-19 (decisiones de `/speckit-analyze`)

- Q: ¿Qué significa exactamente que la contraseña "contiene el correo o el nombre"? → A: Se rechaza si contiene, sin distinguir mayúsculas, la parte local completa del correo (si tiene 4 o más caracteres) o alguna palabra completa del nombre de 4 o más caracteres (FR-016).
- Q: ¿A qué límite cuentan los fallos de la contraseña actual al cambiarla? → A: Solo al límite del par correo + origen, no al límite por origen (FR-030, FR-031).
- Q: ¿Cómo se cumple en esta feature el derecho a exportar los datos (constitución V)? → A: El usuario descarga un fichero JSON con su perfil y los eventos de auditoría que le afectan; las features posteriores amplían la exportación (FR-023a).
- Q: ¿Se guarda la dirección de red completa del cliente en la auditoría y en los logs? → A: No: solo su red reducida (IPv4 /24, IPv6 /48). Para el límite de intentos se guarda un seudónimo no reversible de la dirección (FR-034, FR-035).
- Q: ¿Qué pasa si se crea un administrador por CLI con un correo que tiene una invitación pendiente? → A: El comando lo rechaza; y si aun así el correo ya existe al canjear la invitación, el alta falla con el mensaje genérico sin consumir el código.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Crear el primer administrador desde la línea de comandos (Priority: P1)

El operador que despliega la aplicación crea una cuenta de administrador desde la línea de
comandos indicando un correo y una contraseña. Es la única vía para crear administradores.

**Why this priority**: sin un administrador nadie puede emitir invitaciones, así que sin esto la
aplicación queda inutilizable.

**Independent Test**: ejecutar el comando en una instalación vacía e iniciar sesión en la web con
esas credenciales.

**Acceptance Scenarios**:

1. **Given** una instalación sin usuarios, **When** el operador ejecuta el comando con un correo
   válido e introduce dos veces una contraseña válida, **Then** se crea un usuario con rol de
   administrador y el comando confirma el alta sin mostrar la contraseña.
2. **Given** que ya existe un usuario con ese correo, **When** el operador ejecuta el comando,
   **Then** el comando falla con un mensaje claro y no se modifica ningún usuario.
3. **Given** una contraseña que no cumple la política, **When** el operador la introduce,
   **Then** el comando la rechaza indicando qué regla incumple y no crea el usuario.
4. **Given** el comando, **When** el operador lo ejecuta, **Then** la contraseña se pide de forma
   interactiva sin eco y nunca se acepta como argumento de la línea de comandos.

---

### User Story 2 - Generar una invitación (Priority: P1)

El administrador genera desde la web un código de invitación de un solo uso para un correo
concreto, con una caducidad configurable (7 días por defecto) y una nota opcional. La aplicación muestra el código una única vez y el administrador lo entrega por sus
propios medios.

**Why this priority**: es la única forma de que entren usuarios nuevos.

**Independent Test**: con un administrador, generar una invitación, comprobar que el código se
muestra una sola vez y que aparece como pendiente en el listado de invitaciones.

**Acceptance Scenarios**:

1. **Given** un administrador con sesión iniciada, **When** genera una invitación para un correo
   sin indicar la caducidad, **Then** obtiene un código ligado a ese correo, que caduca a los 7
   días y que aparece como "pendiente".
2. **Given** un administrador, **When** genera una invitación con una caducidad de 2 días,
   **Then** el código caduca a los 2 días.
3. **Given** una invitación ya generada, **When** el administrador vuelve a consultarla,
   **Then** ve el correo invitado, su estado, la nota y las fechas, pero no el código.
4. **Given** un usuario sin rol de administrador, **When** intenta generar una invitación,
   **Then** la petición se rechaza.
5. **Given** un correo que ya pertenece a un usuario o que ya tiene una invitación pendiente,
   **When** el administrador intenta invitarlo, **Then** se rechaza con un mensaje que lo explica.
   El administrador puede revocar la pendiente y generar otra.

---

### User Story 3 - Completar el alta con un código (Priority: P1)

La persona invitada abre la página de alta e introduce el código. El formulario le muestra el
correo de la invitación, ya rellenado y sin poder cambiarlo. Ella introduce su nombre y una
contraseña, y entra directamente en la aplicación con la sesión iniciada.

**Why this priority**: es el camino para que un usuario real empiece a usar la aplicación.

**Independent Test**: con un código válido, completar el alta y comprobar que se accede a la
aplicación; repetir con el mismo código y comprobar que se rechaza.

**Acceptance Scenarios**:

1. **Given** un código válido y sin usar, **When** la persona completa el formulario con datos
   válidos, **Then** se crea su usuario con rol normal, el código queda consumido y la persona
   entra en la aplicación con la sesión iniciada.
2. **Given** un código ya usado, caducado, revocado o inexistente, **When** se intenta el alta,
   **Then** se rechaza con un mensaje genérico ("código no válido o caducado") que no distingue
   entre esos casos.
3. **Given** un código válido, **When** se envía el alta con un correo distinto del de la
   invitación (manipulando el formulario), **Then** se rechaza con el mensaje genérico y el código
   no se consume.
4. **Given** una contraseña trivial o demasiado corta, **When** se intenta el alta, **Then** se
   rechaza indicando la regla incumplida y el código no se consume.
5. **Given** dos altas simultáneas con el mismo código, **When** ambas se envían a la vez,
   **Then** como máximo una tiene éxito.

---

### User Story 4 - Iniciar y cerrar sesión (Priority: P1)

Un usuario inicia sesión con su correo y su contraseña, la cierra cuando quiere, y la sesión
caduca automáticamente tras un periodo de inactividad.

**Why this priority**: es el control de acceso básico a cualquier dato de la aplicación.

**Independent Test**: iniciar sesión, navegar, cerrar sesión y comprobar que las páginas
protegidas ya no son accesibles; dejar pasar el tiempo de inactividad y comprobar lo mismo.

**Acceptance Scenarios**:

1. **Given** un usuario activo, **When** introduce las credenciales correctas, **Then** accede a
   la aplicación.
2. **Given** credenciales incorrectas, un correo inexistente o un usuario desactivado, **When**
   se intenta iniciar sesión, **Then** el mensaje es el mismo en todos los casos ("correo o
   contraseña incorrectos") y el tiempo de respuesta no permite distinguirlos.
3. **Given** una sesión iniciada, **When** el usuario cierra sesión, **Then** la sesión queda
   invalidada y no puede reutilizarse.
4. **Given** una sesión sin actividad durante más del tiempo configurado (30 minutos por
   defecto), **When** el usuario hace una petición, **Then** se le redirige al inicio de sesión.
5. **Given** 5 intentos fallidos para un mismo correo desde un mismo origen en 15 minutos,
   **When** se hace un sexto intento desde ese origen, aunque sea con la contraseña correcta,
   **Then** se rechaza con el mensaje genérico hasta que pase el periodo de bloqueo. Desde otro
   origen, el usuario legítimo sigue pudiendo entrar.
6. **Given** 20 intentos fallidos desde un mismo origen en 15 minutos, **When** se hace otro
   intento desde ese origen, **Then** se rechaza hasta que pase el periodo de bloqueo.
7. **Given** más de 50 intentos fallidos en una hora para un mismo correo, sumando todos los
   orígenes, **When** se hace un nuevo intento, **Then** la respuesta se retrasa de forma
   creciente, pero con la contraseña correcta se sigue pudiendo entrar.

---

### User Story 5 - Cambiar la contraseña, editar el nombre y exportar mis datos (Priority: P2)

Un usuario edita su nombre visible, cambia su contraseña indicando la actual y descarga una copia
de sus datos.

**Why this priority**: es mantenimiento básico de la cuenta, pero no bloquea el uso inicial.

**Independent Test**: cambiar el nombre y la contraseña, cerrar sesión y entrar con la contraseña
nueva; descargar la exportación y comprobar que contiene el perfil.

**Acceptance Scenarios**:

1. **Given** una sesión iniciada, **When** el usuario cambia su nombre por uno válido, **Then** el
   nuevo nombre se muestra en la aplicación.
2. **Given** una sesión iniciada, **When** el usuario introduce la contraseña actual correcta y
   una nueva que cumple la política, **Then** la contraseña cambia, sus demás sesiones se cierran
   y la actual sigue abierta.
3. **Given** una contraseña actual incorrecta, **When** el usuario intenta cambiarla, **Then** se
   rechaza y el intento cuenta para el límite de intentos de su correo desde ese origen (FR-030).
4. **Given** una sesión iniciada, **When** el usuario pide exportar sus datos, **Then** descarga un
   fichero con su nombre, su correo, su rol, su estado, sus fechas de alta y de último inicio de
   sesión y los eventos de auditoría que le afectan, sin ningún dato de otros usuarios ni su
   credencial.

---

### User Story 6 - Administrar usuarios e invitaciones (Priority: P2)

El administrador ve el listado de usuarios y el de invitaciones, desactiva o reactiva usuarios y
revoca invitaciones pendientes.

**Why this priority**: permite cortar el acceso a quien ya no deba tenerlo y anular invitaciones
entregadas por error.

**Independent Test**: desactivar a un usuario con sesión abierta y comprobar que su siguiente
petición se rechaza; reactivarlo y comprobar que puede volver a entrar.

**Acceptance Scenarios**:

1. **Given** un administrador, **When** abre el listado de usuarios, **Then** ve el nombre, el
   correo, el rol, el estado (activo o desactivado), la fecha de alta y el último inicio de sesión
   de cada usuario. No ve datos de entrenamiento ni de salud.
2. **Given** un usuario activo con sesiones abiertas, **When** el administrador lo desactiva,
   **Then** todas sus sesiones se invalidan inmediatamente, no puede volver a iniciar sesión, se
   pausan las descargas de sus cuentas Garmin y ningún entrenador ve sus datos, aunque tenga su
   consentimiento.
3. **Given** un usuario desactivado, **When** el administrador lo reactiva, **Then** puede
   volver a iniciar sesión con su contraseña, sus descargas se reanudan y los consentimientos que
   tenía dados vuelven a surtir efecto, sin haber perdido ningún dato.
4. **Given** una invitación pendiente, **When** el administrador la revoca, **Then** su código
   deja de valer.
5. **Given** el listado de invitaciones, **When** el administrador lo consulta, **Then** ve el
   correo invitado, su estado (pendiente, usada, caducada o revocada), su nota, la fecha de
   creación, la de caducidad y, si se usó, qué usuario la usó.
6. **Given** que solo queda un administrador activo, **When** se intenta desactivarlo, **Then**
   se rechaza. Ningún administrador puede desactivarse a sí mismo.
7. **Given** un usuario normal desactivado, **When** el administrador pide borrarlo y confirma
   escribiendo el correo de ese usuario, **Then** se eliminan el usuario y todos sus datos, igual
   que en el borrado propio (FR-028), y queda un evento de auditoría con el administrador que lo
   hizo.
8. **Given** un usuario activo o un administrador, **When** el administrador intenta borrarlo,
   **Then** se rechaza; un usuario activo primero tiene que desactivarse.

---

### User Story 7 - Eliminar mi usuario (Priority: P2)

Un usuario elimina su propio usuario tras una confirmación explícita. Se borran todos sus datos:
cuentas Garmin vinculadas, datos descargados, ficheros crudos, consentimientos y membresías.

**Why this priority**: es el derecho de supresión de datos personales y de salud.

**Independent Test**: crear un usuario con datos asociados, eliminarlo y comprobar que no queda
ningún dato suyo y que sus credenciales ya no sirven.

**Acceptance Scenarios**:

1. **Given** una sesión iniciada, **When** el usuario pide eliminar su cuenta, **Then** la
   aplicación le explica qué se borrará y le pide su contraseña actual y una confirmación
   explícita (por ejemplo, escribir "ELIMINAR").
2. **Given** la confirmación correcta, **When** se ejecuta el borrado, **Then** se eliminan el
   usuario y todos sus datos asociados, se cierran todas sus sesiones y se le lleva a la página
   pública con un aviso de que el borrado se ha completado.
3. **Given** una contraseña o una confirmación incorrectas, **When** se intenta el borrado,
   **Then** no se borra nada.
4. **Given** que el usuario es el único administrador activo, **When** intenta eliminarse,
   **Then** se rechaza con un mensaje que explica el motivo.
5. **Given** un usuario eliminado, **When** se intenta iniciar sesión con su correo, **Then** el
   resultado es el mismo que con un correo inexistente.

---

### User Story 8 - Restablecer la contraseña con un código del administrador (Priority: P3)

Cuando un usuario olvida su contraseña, el administrador genera para él un código de
restablecimiento de un solo uso y se lo entrega por sus propios medios. El usuario lo introduce,
junto con su correo y una contraseña nueva, en una página pública.

**Why this priority**: es útil, pero poco frecuente, y tiene un camino alternativo manual.

**Independent Test**: generar un código para un usuario, usarlo para fijar una contraseña nueva y
comprobar que la antigua deja de valer y que el código no puede reutilizarse.

**Acceptance Scenarios**:

1. **Given** un usuario activo, **When** el administrador genera un código de restablecimiento,
   **Then** el código se muestra una única vez y caduca a las 24 horas.
2. **Given** un código válido, **When** el usuario lo introduce con su correo y una contraseña
   nueva válida, **Then** la contraseña cambia, todas sus sesiones se cierran y el código queda
   consumido.
3. **Given** un código usado, caducado, sustituido por otro más reciente o que no corresponde a
   ese correo, **When** se intenta usar, **Then** se rechaza con un mensaje genérico.
4. **Given** un usuario desactivado, **When** el administrador intenta generarle un código,
   **Then** se rechaza.

### Edge Cases

- Los intentos de canjear códigos de invitación o de restablecimiento cuentan para un límite de
  intentos por origen, que impide probarlos por fuerza bruta.
- Si una invitación caduca mientras la persona está rellenando el formulario, el alta se rechaza
  con el mensaje genérico.
- Si un usuario es desactivado en mitad de una petición, la siguiente petición se rechaza.
- Si un usuario es desactivado mientras se descargan datos de una de sus cuentas Garmin, la
  descarga se detiene limpiamente en su siguiente punto de control y se reanuda al reactivarlo.
- Si se genera un segundo código de restablecimiento para el mismo usuario, el primero queda
  anulado.
- Si se pide eliminar un usuario y el borrado falla a mitad, la operación se puede reintentar
  hasta completarse y el usuario no puede iniciar sesión mientras tanto.
- Un correo con mayúsculas o espacios alrededor se trata igual que su forma normalizada, tanto en
  el alta como en el inicio de sesión.
- Si faltan secretos obligatorios al arrancar, la aplicación no atiende ninguna petición.
- Si un correo con una invitación pendiente se registra por otra vía (un administrador creado por
  línea de comandos), el comando lo rechaza; si aun así el correo ya existe al canjear la
  invitación, el alta se rechaza con el mensaje genérico y el código no se consume.
- Si un usuario con un código de restablecimiento pendiente es desactivado o entra en borrado, el
  código queda anulado y no puede usarse aunque se reactive.

## Requirements *(mandatory)*

### Functional Requirements

**Arranque y configuración**

- **FR-001**: La aplicación MUST negarse a arrancar si falta algún secreto obligatorio. Debe
  mostrar un mensaje que nombre los secretos que faltan sin revelar ningún valor.
- **FR-002**: Las duraciones y los límites de esta feature MUST ser configurables, con estos
  valores por defecto:
  - caducidad de las invitaciones: 7 días;
  - caducidad de los códigos de restablecimiento: 24 horas;
  - inactividad de la sesión: 30 minutos;
  - duración máxima de la sesión: 12 horas;
  - límites de intentos: los indicados en FR-030, FR-030a y FR-031.

**Administradores**

- **FR-003**: El sistema MUST permitir crear un usuario administrador desde la línea de comandos
  con un correo y una contraseña. La contraseña se pide de forma interactiva, sin eco y con
  confirmación.
- **FR-004**: Los administradores MUST crearse solo desde la línea de comandos; ninguna acción de
  la web otorga el rol de administrador.
- **FR-004a**: Un usuario administrador MUST NOT poder vincular cuentas Garmin, solicitar el
  ingreso en un club ni ser miembro de un club con ningún rol (ni atleta ni entrenador). El rol de
  un usuario no cambia después de crearse.

**Invitaciones**

- **FR-005**: Un administrador MUST poder generar invitaciones de un solo uso, cada una ligada a un
  correo obligatorio, con una caducidad opcional (7 días si no se indica) y una nota opcional.
- **FR-005a**: El sistema MUST rechazar una invitación para un correo que ya pertenece a un usuario
  o que ya tiene otra invitación pendiente.
- **FR-006**: El código de invitación MUST mostrarse una única vez, al generarse, y MUST tener
  entropía suficiente para que no pueda adivinarse.
- **FR-007**: El sistema MUST almacenar los códigos de invitación solo de forma no reversible.
- **FR-008**: El sistema MUST rechazar los códigos usados, caducados, revocados o inexistentes con
  un mismo mensaje genérico.
- **FR-009**: El consumo de un código MUST ser atómico: aunque haya peticiones simultáneas, un
  código da lugar como máximo a un alta.
- **FR-010**: Un administrador MUST poder revocar una invitación pendiente.

**Alta**

- **FR-011**: El alta con código MUST pedir el nombre y la contraseña, y MUST usar como correo
  del usuario el de la invitación. El sistema MUST rechazar cualquier alta con un correo
  distinto. Si tiene éxito, crea un usuario con rol normal y deja su sesión iniciada.
- **FR-012**: Cada usuario MUST tener un identificador interno estable, independiente de su
  correo, de su nombre y de sus cuentas Garmin.
- **FR-013**: El correo MUST ser único, comparándolo sin distinguir mayúsculas y sin espacios
  alrededor.
- **FR-014**: Un alta rechazada por datos no válidos MUST NOT consumir el código.

**Política de contraseñas**

- **FR-015**: Las contraseñas MUST tener entre 12 y 128 caracteres.
- **FR-016**: Una contraseña MUST rechazarse si:
  - aparece en una lista de contraseñas comunes;
  - contiene, sin distinguir mayúsculas, la parte local completa del correo (lo que va antes de
    la `@`, si tiene 4 o más caracteres);
  - contiene, sin distinguir mayúsculas, alguna palabra completa del nombre que tenga 4 o más
    caracteres.
- **FR-017**: El sistema MUST almacenar las contraseñas solo de forma no reversible, con un
  algoritmo diseñado para contraseñas.

**Sesión**

- **FR-018**: Los usuarios activos MUST poder iniciar sesión con su correo y su contraseña, y
  cerrarla.
- **FR-019**: Al cerrar sesión, la sesión MUST invalidarse en el servidor.
- **FR-020**: Las sesiones MUST caducar tras el tiempo de inactividad configurado y al alcanzar
  la duración máxima, aunque haya actividad.
- **FR-021**: Al iniciar sesión, el sistema MUST renovar el identificador de sesión.

**Perfil**

- **FR-022**: Un usuario MUST poder editar su nombre visible.
- **FR-023**: Un usuario MUST poder cambiar su contraseña indicando la actual. El cambio cierra
  todas sus demás sesiones.
- **FR-023a**: Un usuario MUST poder descargar una exportación de sus datos en un formato legible
  por máquina, con su perfil (nombre, correo, rol, estado, fecha de alta y último inicio de
  sesión) y los eventos de auditoría de los que es sujeto. La exportación MUST NOT incluir su
  credencial ni datos de otros usuarios. Cualquier dato de usuario que añadan features futuras
  MUST quedar incluido en esta exportación.

**Administración**

- **FR-024**: Un administrador MUST poder listar usuarios (nombre, correo, rol, estado, fecha de
  alta y último inicio de sesión) e invitaciones (correo invitado, estado, nota, fechas y
  usuario que la usó).
- **FR-025**: Un administrador MUST poder desactivar y reactivar usuarios.
- **FR-026**: Desactivar a un usuario MUST, de inmediato:
  - invalidar todas sus sesiones e impedir que vuelva a iniciar sesión;
  - pausar las descargas programadas o pendientes de sus cuentas Garmin (un trabajo en curso se
    detiene en su siguiente punto de control);
  - hacer que ningún entrenador vea sus datos, aunque tenga su consentimiento.

  Los datos y los consentimientos se conservan. Al reactivar al usuario, todo se restablece. Las
  features de sincronización y de consentimiento MUST respetar este estado.
- **FR-027**: El sistema MUST impedir desactivar o eliminar al último administrador activo, y que
  un administrador se desactive a sí mismo.

**Borrado**

- **FR-028**: Un usuario MUST poder eliminar su propio usuario indicando su contraseña y una
  confirmación explícita. El borrado elimina:
  - su usuario;
  - sus cuentas Garmin vinculadas;
  - los datos descargados y los ficheros crudos;
  - sus consentimientos y membresías;
  - sus sesiones.

  Cualquier dato de usuario que añadan features futuras MUST quedar incluido en este borrado.
- **FR-028a**: Un administrador MUST poder borrar a un usuario normal que esté desactivado,
  confirmando con el correo de ese usuario. El borrado tiene el mismo alcance que FR-028. El
  sistema MUST rechazar el borrado por un administrador de usuarios activos y de otros
  administradores.

**Restablecimiento**

- **FR-029**: Un administrador MUST poder generar un código de restablecimiento para un usuario
  activo. El código:
  - se muestra una sola vez;
  - se almacena solo de forma no reversible;
  - caduca a las 24 horas por defecto;
  - es de un solo uso;
  - anula cualquier código anterior del mismo usuario.

  Al usarlo, el usuario fija una contraseña nueva y se cierran todas sus sesiones. El código solo
  vale mientras el usuario está activo: desactivarlo o iniciar su borrado anula los códigos
  pendientes.

**Protección frente a abusos**

- **FR-030**: El sistema MUST limitar los intentos fallidos por correo y origen: tras 5 fallos en
  15 minutos para el mismo par correo + origen, ese par queda bloqueado 15 minutos. Cuentan los
  fallos de inicio de sesión y los de la contraseña actual al cambiarla (US5). Un inicio de sesión
  correcto desde ese par reinicia su recuento.
- **FR-030a**: El sistema MUST aplicar además un límite global por correo: a partir de 50 fallos en
  una hora, sumando todos los orígenes, cada nuevo intento para ese correo recibe un retardo
  creciente, con un máximo de 10 segundos. Nunca hay un bloqueo total que impida entrar con la
  contraseña correcta. Al superar este límite se registra un evento de auditoría.
- **FR-031**: El sistema MUST limitar los intentos fallidos por origen: 20 fallos en 15 minutos.
  Cuentan los fallos de inicio de sesión y de canje de códigos (no los de la contraseña actual,
  que ya limita FR-030).
- **FR-032**: Los mensajes de error del inicio de sesión, el alta y el restablecimiento MUST NOT
  revelar si un correo está registrado ni si un usuario está desactivado o bloqueado.
- **FR-033**: Toda acción que modifique estado MUST estar protegida contra peticiones
  falsificadas desde otros sitios.

**Auditoría**

- **FR-034**: El sistema MUST registrar un evento de auditoría, de solo inserción, para cada uno
  de estos hechos:
  - creación de un administrador;
  - generación y revocación de invitaciones;
  - altas;
  - inicios de sesión correctos y fallidos;
  - bloqueos por exceso de intentos;
  - cambios de contraseña;
  - generación y uso de códigos de restablecimiento;
  - desactivaciones y reactivaciones;
  - borrados de usuario, indicando si los pidió el propio usuario o un administrador.

  - exportaciones de datos.

  Cada evento incluye la fecha y hora, el tipo, el usuario que actúa, el usuario afectado (si lo
  hay) y el origen reducido a su red (IPv4 /24, IPv6 /48), nunca la dirección completa.
- **FR-035**: Los eventos de auditoría y los logs MUST NOT contener contraseñas, códigos,
  identificadores de sesión ni direcciones de red completas en claro, y los logs tampoco correos.
  Tras borrar a un usuario, sus eventos de auditoría solo conservan su identificador interno, sin
  correo ni nombre. Los registros usados para limitar intentos guardan el origen solo de forma no
  reversible y se purgan a las 24 horas.

### Key Entities

- **Usuario**: persona que usa la aplicación. Atributos: identificador interno estable, nombre
  visible, correo único, credencial no reversible, rol fijo (usuario o administrador; el
  administrador nunca tiene cuentas Garmin ni membresías), estado (activo, desactivado o
  borrado pendiente), fecha de alta y último inicio de sesión. Más adelante se relacionará con cuentas
  Garmin, clubes y consentimientos.
- **Invitación**: código de un solo uso para darse de alta. Atributos: código no reversible,
  correo invitado, administrador que la creó, nota, fecha de creación, fecha de caducidad, estado (pendiente,
  usada, caducada o revocada) y usuario creado al usarla.
- **Código de restablecimiento**: código de un solo uso para fijar una contraseña nueva.
  Atributos: código no reversible, usuario destinatario, administrador emisor, fecha de creación,
  fecha de caducidad y estado (pendiente, usado, caducado o sustituido).
- **Sesión**: acceso autenticado de un usuario. Atributos: usuario, inicio, última actividad y
  caducidad absoluta. Una sesión cerrada o caducada se elimina.
- **Evento de auditoría**: registro inmutable de una acción relevante para la seguridad.
  Atributos: fecha y hora, tipo, usuario que actúa, usuario afectado, origen reducido a su red y
  detalles sin datos sensibles.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Una persona invitada completa su alta, desde que abre la página hasta que entra en
  la aplicación, en menos de 2 minutos.
- **SC-002**: El 100 % de los intentos con códigos usados, caducados, revocados o sustituidos se
  rechazan, incluidos los intentos simultáneos con un mismo código.
- **SC-003**: Tras desactivar a un usuario, el 0 % de sus peticiones posteriores se aceptan,
  incluidas las de sesiones abiertas antes de la desactivación, y no se hace ninguna petición
  nueva a Garmin para sus cuentas.
- **SC-004**: Una revisión de la base de datos y de los logs tras un ciclo completo (alta, inicio
  de sesión, cambio de contraseña, restablecimiento y borrado) no encuentra ninguna contraseña,
  código, identificador de sesión ni secreto de configuración en claro, ni direcciones de red
  completas.
- **SC-005**: Las respuestas a intentos fallidos con un correo existente y con uno inexistente no
  se distinguen por el mensaje ni por el tiempo de respuesta.
- **SC-006**: Tras eliminar un usuario, no queda ningún dato suyo ni ningún fichero crudo
  asociado, salvo los eventos de auditoría con su identificador interno.
- **SC-007**: Un operador pone en marcha una instalación nueva con un administrador funcional en
  menos de 5 minutos.

## Assumptions

- Hay dos roles en esta feature: usuario y administrador. Entrenadores, clubes y consentimientos
  se definen en features posteriores, que se engancharán al borrado de usuario (FR-028).
- El correo no puede cambiarse en esta feature.
- La aplicación no envía correos: invitaciones y códigos de restablecimiento se entregan a mano.
  No hay recuperación de contraseña automática.
- El administrador solo puede borrar a usuarios normales ya desactivados (FR-028a), por ejemplo
  para atender una petición de supresión de alguien que ya no puede iniciar sesión. Cualquier otro
  borrado lo hace el propio usuario.
- Las cuentas de administrador sirven solo para administrar (ver FR-004a). Quien además entrena
  o compite usa un segundo usuario normal con otro correo. Así, la regla de la constitución de que
  el administrador no ve datos de entrenamiento ni de salud se cumple sin excepciones.
- La lista de contraseñas comunes se incluye con la aplicación y no requiere consultar servicios
  externos.
- Por "origen" se entiende la dirección de red del cliente tal como la ve la aplicación detrás de
  su proxy de confianza.
- **Verificación diferida**: algunas partes de los requisitos afectan a entidades que aún no
  existen y se verifican en la feature que las introduce, cuyo análisis MUST comprobarlas:
  - FR-004a (administradores sin cuentas Garmin ni membresías): vinculación de cuentas Garmin y
    clubes;
  - FR-026 y SC-003 (pausa de descargas): sincronización con Garmin; FR-026 (entrenadores sin
    acceso): clubes, entrenadores y consentimiento;
  - FR-028, FR-028a y SC-006 (cuentas Garmin, datos descargados, ficheros crudos,
    consentimientos y membresías): cada feature que los introduce registra su paso de borrado;
  - FR-023a (exportación de esos mismos datos): cada feature que los introduce amplía la
    exportación.
- En esta feature no se contemplan la autenticación de dos factores ni el inicio de sesión con
  proveedores externos.
