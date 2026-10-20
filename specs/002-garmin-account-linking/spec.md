# Feature Specification: Vinculación y gestión de cuentas Garmin

**Feature Branch**: `002-garmin-account-linking`

**Created**: 2026-10-20

**Status**: Draft

**Input**: User description: "Vinculación y gestión de cuentas Garmin desde la web de garmin-hub.
Cada usuario puede vincular una o varias cuentas Garmin Connect propias, cada una con un
identificador interno estable y un alias elegido por el usuario; un entrenador puede no tener
ninguna. Historias: vincular una cuenta con alias, correo y contraseña de Garmin y código MFA si
Garmin lo pide, descartando la contraseña y conservando solo el token cifrado; ver mis cuentas
con alias, estado, último login y última sincronización; ver y gestionar solo mis cuentas;
reautenticar una cuenta caducada sin perder datos; desvincular conservando o borrando los datos
descargados; aceptar antes de vincular un texto claro sobre qué datos se descargan y quién
podría verlos; comprobar que una cuenta sigue funcionando sin descargar datos."

## Clarifications

### Session 2026-10-20

- Q: Cuando un usuario desvincula una cuenta Garmin pero elige conservar sus datos, ¿pueden seguir viéndolos los entrenadores a los que les dio consentimiento? → A: Sí: los consentimientos siguen vigentes hasta que el usuario los revoque; desvincular solo detiene las descargas.
- Q: Si un usuario desvincula una cuenta Garmin conservando sus datos, ¿puede otro usuario vincular después esa misma cuenta Garmin? → A: Sí: la vinculación nueva crea una cuenta distinta con otro identificador interno; los datos conservados siguen siendo del primer usuario.
- Q: ¿Guarda la aplicación el correo de la cuenta Garmin para mostrárselo al usuario, o solo el alias? → A: Solo el alias: el correo de Garmin se usa durante el login y se descarta como la contraseña; para evitar duplicados solo se guarda el identificador que da Garmin.
- Q: Cuando una cuenta pasa a "Requiere reautenticación" o a "Error", ¿cómo se entera el usuario? → A: En el listado y, además, con un aviso en la página de inicio mientras haya alguna cuenta en esos estados, con enlace para resolverlo; sin correo electrónico.
- Q: Cuando se publica una versión nueva del aviso de datos, ¿se siguen descargando datos de las cuentas ya vinculadas mientras el usuario no acepte la versión nueva? → A: Sí, pero la página de inicio muestra un aviso para aceptar la versión nueva, y esta se exige al vincular o reautenticar.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Vincular una cuenta Garmin (Priority: P1)

Un usuario vincula una cuenta Garmin Connect propia desde la web. Indica un alias, el correo y la
contraseña de esa cuenta de Garmin y, si Garmin lo pide, el código de verificación en dos pasos
(MFA). Si el inicio de sesión en Garmin es correcto, la cuenta queda vinculada: la aplicación
descarta la contraseña y solo conserva, cifrado, el acceso que Garmin le concede.

**Why this priority**: sin cuentas vinculadas la aplicación no puede descargar ningún dato; es la
puerta de entrada de todo lo demás.

**Independent Test**: con un usuario y una cuenta Garmin de prueba (con y sin MFA), completar la
vinculación y comprobar que la cuenta aparece como "Válida" y que en ningún sitio queda la
contraseña de Garmin.

**Acceptance Scenarios**:

1. **Given** un usuario que ha aceptado el aviso de datos (US6), **When** introduce un alias, un
   correo y una contraseña de Garmin correctos de una cuenta sin MFA, **Then** la cuenta queda
   vinculada con estado "Válida" y la fecha del último login, y la contraseña no se guarda.
2. **Given** una cuenta Garmin con MFA, **When** el usuario introduce correo y contraseña
   correctos, **Then** la aplicación le pide el código MFA; al introducir el código correcto la
   cuenta queda vinculada.
3. **Given** una vinculación pendiente de MFA, **When** pasan más de 5 minutos sin introducir el
   código, **Then** el intento caduca, se descarta todo lo recibido y el usuario debe empezar de
   nuevo.
4. **Given** un código MFA incorrecto, **When** el usuario lo envía, **Then** se le indica que el
   código no es correcto y puede volver a intentarlo mientras el intento no haya caducado.
5. **Given** credenciales de Garmin incorrectas, **When** el usuario intenta vincular, **Then**
   ve un mensaje claro ("Garmin no acepta ese correo o contraseña") y no se crea ninguna cuenta.
6. **Given** una cuenta Garmin ya vinculada a otro usuario, **When** un usuario intenta
   vincularla, **Then** se rechaza con un mensaje que no revela quién la tiene vinculada.
7. **Given** una cuenta Garmin ya vinculada al mismo usuario, **When** intenta vincularla otra
   vez, **Then** se rechaza indicando que ya está vinculada y con qué alias.
8. **Given** un administrador, **When** intenta vincular una cuenta Garmin, **Then** se rechaza
   (feature 001, FR-004a).

---

### User Story 2 - Ver mis cuentas Garmin (Priority: P1)

El usuario ve el listado de sus cuentas Garmin con el alias, el estado (válida, requiere
reautenticación, error, desvinculada con datos conservados o borrado pendiente), la fecha del último login correcto en Garmin y la de la última
sincronización.

**Why this priority**: es la forma de saber qué cuentas tiene y si alguna necesita atención.

**Independent Test**: con un usuario con varias cuentas en estados distintos, abrir el listado y
comprobar que muestra cada una con su estado y sus fechas.

**Acceptance Scenarios**:

1. **Given** un usuario con dos cuentas vinculadas, **When** abre "Mis cuentas Garmin", **Then**
   ve las dos con alias, estado, fecha del último login y fecha de la última sincronización
   ("Nunca" si todavía no se ha sincronizado).
2. **Given** una cuenta en estado "Requiere reautenticación" o "Error", **When** el usuario ve el
   listado, **Then** la cuenta lo indica claramente y ofrece la acción para resolverlo.
3. **Given** un usuario sin cuentas, **When** abre el listado, **Then** ve un mensaje que explica
   que no tiene cuentas y cómo vincular una. Un entrenador puede usar la aplicación sin cuentas.
4. **Given** una cuenta desvinculada conservando sus datos (US5), **When** el usuario ve el
   listado, **Then** aparece como "Desvinculada (datos conservados)".
5. **Given** un usuario con alguna cuenta en "Requiere reautenticación" o "Error", **When**
   entra en la página de inicio, **Then** ve un aviso con el alias de cada cuenta afectada y un
   enlace para resolverlo; cuando ya no queda ninguna en esos estados, el aviso desaparece.

---

### User Story 3 - Solo veo y gestiono mis propias cuentas (Priority: P1)

Cada usuario solo puede ver y gestionar las cuentas Garmin que él mismo ha vinculado. Nadie más,
ni otro usuario ni el administrador, puede verlas ni actuar sobre ellas desde la web.

**Why this priority**: las cuentas dan acceso a datos personales y de salud; una fuga entre
usuarios sería grave.

**Independent Test**: con dos usuarios con cuentas, comprobar que cada uno solo ve las suyas y
que cualquier intento de acceder a una cuenta ajena por su identificador responde igual que si
no existiera.

**Acceptance Scenarios**:

1. **Given** dos usuarios A y B con cuentas, **When** A abre su listado, **Then** no ve ninguna
   cuenta de B.
2. **Given** el identificador de una cuenta de B, **When** A intenta ver, reautenticar,
   comprobar o desvincular esa cuenta, **Then** la respuesta es la misma que para una cuenta
   inexistente y no se modifica nada.
3. **Given** un administrador, **When** usa la aplicación, **Then** no tiene ninguna vista ni
   acción sobre las cuentas Garmin de los usuarios.

---

### User Story 4 - Reautenticar una cuenta caducada (Priority: P2)

Cuando Garmin deja de aceptar el acceso guardado, la cuenta pasa a "Requiere reautenticación". El
usuario vuelve a introducir el correo y la contraseña de Garmin (y el código MFA si se lo pide) y
la cuenta vuelve a estar "Válida", sin perder ningún dato descargado.

**Why this priority**: los accesos caducan con el tiempo; sin esto el usuario tendría que
desvincular y volver a vincular.

**Independent Test**: con una cuenta en "Requiere reautenticación" y datos asociados,
reautenticarla y comprobar que vuelve a "Válida" con los mismos datos e identificador interno.

**Acceptance Scenarios**:

1. **Given** una cuenta en "Requiere reautenticación", **When** el usuario introduce el correo y la
   contraseña correctos (y el MFA si se pide), **Then** la cuenta vuelve a "Válida", conserva
   su identificador interno, su alias y sus datos, y se actualiza la fecha del último login.
2. **Given** una reautenticación, **When** las credenciales corresponden a una cuenta Garmin
   distinta de la vinculada, **Then** se rechaza y la cuenta sigue como estaba.
3. **Given** un usuario con varias cuentas, **When** una de ellas caduca, **Then** las demás
   siguen "Válidas" y funcionando.
4. **Given** una cuenta "Válida", **When** el usuario quiere reautenticarla igualmente, **Then**
   puede hacerlo (por ejemplo, tras cambiar su contraseña en Garmin).

---

### User Story 5 - Desvincular una cuenta (Priority: P2)

El usuario desvincula una cuenta y elige entre conservar o borrar los datos descargados de ella.
En ambos casos se elimina el acceso guardado y la aplicación deja de descargar datos de esa
cuenta. Si elige borrar, se eliminan sus datos de la base de datos y sus ficheros crudos.

**Why this priority**: es parte del control del usuario sobre sus datos (derecho de supresión).

**Independent Test**: desvincular una cuenta con datos eligiendo "borrar" y comprobar que no
queda nada de ella; desvincular otra eligiendo "conservar" y comprobar que sus datos siguen
disponibles para el usuario y que no queda ningún acceso guardado.

**Acceptance Scenarios**:

1. **Given** una cuenta vinculada, **When** el usuario elige desvincular, **Then** la aplicación
   le explica las dos opciones (incluido que, si conserva los datos, los entrenadores con
   consentimiento seguirán viéndolos) y le pide confirmación explícita.
2. **Given** la opción "borrar datos" confirmada, **When** termina la desvinculación, **Then** se
   eliminan la cuenta, su acceso guardado, todos sus datos descargados y sus ficheros crudos.
3. **Given** la opción "conservar datos" confirmada, **When** termina la desvinculación, **Then**
   se elimina el acceso guardado, la cuenta queda "Desvinculada (datos conservados)" y sus datos
   siguen siendo visibles para el usuario y para los entrenadores con consentimiento vigente,
   pero no se descarga nada nuevo.
4. **Given** una cuenta "Desvinculada (datos conservados)", **When** el mismo usuario la vuelve a
   vincular con la misma cuenta Garmin, **Then** recupera el mismo identificador interno y los
   datos conservados. Si entretanto otro usuario ha vinculado esa cuenta Garmin, se rechaza como
   cualquier cuenta ya vinculada (FR-007).
5. **Given** una cuenta "Desvinculada (datos conservados)", **When** el usuario decide más tarde
   borrar sus datos, **Then** puede hacerlo con el mismo resultado que en el escenario 2.
6. **Given** un borrado de datos que falla a mitad, **When** se reintenta, **Then** se completa
   sin dejar datos ni ficheros huérfanos.
7. **Given** una cuenta "Desvinculada (datos conservados)" de un usuario A, **When** un usuario B
   vincula la misma cuenta Garmin, **Then** B obtiene una cuenta nueva con otro identificador
   interno, sin acceso a los datos conservados de A.

---

### User Story 6 - Aceptar el aviso de datos antes de vincular (Priority: P2)

Antes de vincular su primera cuenta, el usuario ve un texto claro que explica qué datos se
descargarán de Garmin (actividades, recorridos con GPS y datos de salud como pulsaciones, sueño o
variabilidad cardiaca) y quién podría verlos (solo él y los entrenadores a los que dé su
consentimiento). Debe aceptarlo para continuar.

**Why this priority**: es un requisito de transparencia sobre datos de salud; sin aceptarlo no
se puede vincular.

**Independent Test**: intentar vincular sin aceptar el aviso y comprobar que no se permite;
aceptarlo y comprobar que queda registrado cuándo y qué versión del texto se aceptó.

**Acceptance Scenarios**:

1. **Given** un usuario que no ha aceptado el aviso vigente, **When** empieza a vincular una
   cuenta, **Then** ve el aviso completo y no puede continuar sin marcar que lo acepta.
2. **Given** que el usuario acepta el aviso, **When** continúa, **Then** queda registrado qué
   versión del texto aceptó y cuándo, y no se le vuelve a pedir mientras el texto no cambie.
3. **Given** que el texto del aviso cambia de versión, **When** el usuario vincula o reautentica
   una cuenta, **Then** debe aceptar la versión nueva.
4. **Given** el aviso, **When** el usuario lo lee, **Then** indica que el administrador no puede
   ver sus datos de entrenamiento ni de salud y que puede desvincular la cuenta y borrar sus
   datos cuando quiera.
5. **Given** un usuario con cuentas vinculadas que no ha aceptado la versión nueva del aviso,
   **When** entra en la página de inicio, **Then** ve un aviso con enlace para leerla y aceptarla;
   mientras tanto, las descargas de sus cuentas continúan.

---

### User Story 7 - Comprobar que una cuenta sigue funcionando (Priority: P3)

El usuario pulsa "Comprobar" en una cuenta y la aplicación verifica con Garmin que el acceso
guardado sigue funcionando, sin descargar datos.

**Why this priority**: útil para diagnosticar, pero no imprescindible.

**Independent Test**: comprobar una cuenta válida y otra con el acceso revocado en Garmin, y ver
que el estado se actualiza en cada caso sin que se descargue ningún dato.

**Acceptance Scenarios**:

1. **Given** una cuenta con acceso válido, **When** el usuario la comprueba, **Then** ve que
   funciona y la fecha de la comprobación queda registrada.
2. **Given** una cuenta cuyo acceso Garmin ya no acepta, **When** el usuario la comprueba,
   **Then** la cuenta pasa a "Requiere reautenticación" con un mensaje que lo explica.
3. **Given** un fallo de conexión o un límite de peticiones de Garmin, **When** el usuario
   comprueba, **Then** ve el mensaje correspondiente y el estado de la cuenta no cambia a
   "Requiere reautenticación".
4. **Given** comprobaciones repetidas, **When** el usuario comprueba la misma cuenta varias veces
   seguidas, **Then** la aplicación no hace más de una comprobación por minuto y cuenta.

### Edge Cases

- Si el usuario cierra la página en mitad del paso MFA, el intento caduca a los 5 minutos y no
  queda nada guardado.
- Si dos usuarios intentan vincular a la vez la misma cuenta Garmin, como máximo uno lo consigue.
- Una misma cuenta Garmin puede tener a la vez una vinculación activa de un usuario y cuentas
  "Desvinculadas (datos conservados)" de otros; sus datos nunca se mezclan.
- Si se pierde la conexión con Garmin durante la vinculación, no se crea ninguna cuenta y el
  usuario ve "No se ha podido conectar con Garmin; inténtalo más tarde."
- Si Garmin limita las peticiones o bloquea temporalmente el inicio de sesión, el usuario ve un
  mensaje específico y la aplicación no reintenta automáticamente el login.
- Si falta la clave maestra de cifrado o no corresponde a los accesos guardados, la aplicación no
  arranca (o no puede descifrar) y nunca muestra ni registra el contenido cifrado.
- Si un usuario es desactivado (feature 001), sus cuentas no se pueden gestionar ni comprobar y
  no se descargan datos de ellas hasta que se le reactive.
- Si un usuario se borra (feature 001), se borran todas sus cuentas Garmin, sus accesos, sus datos
  descargados y sus ficheros crudos.
- El alias se compara sin distinguir mayúsculas: un usuario no puede tener dos cuentas con el
  mismo alias.
- Si un acceso caduca mientras se descarga una cuenta, esa cuenta pasa a "Requiere
  reautenticación" y las descargas de las demás cuentas continúan.

## Requirements *(mandatory)*

### Functional Requirements

**Vinculación**

- **FR-001**: Un usuario normal y activo MUST poder vincular una cuenta Garmin indicando un alias,
  el correo y la contraseña de esa cuenta de Garmin.
- **FR-002**: Si Garmin pide un código MFA, el sistema MUST pedírselo al usuario y completar la
  vinculación con él. El estado intermedio de un login pendiente de MFA MUST caducar a los 5
  minutos (configurable) y MUST descartarse al caducar, al completarse o al cancelarse.
- **FR-003**: El sistema MUST NOT persistir la contraseña de Garmin en ningún sitio (base de
  datos, ficheros, logs, auditoría ni mensajes de error). Solo vive en memoria durante el inicio
  de sesión con Garmin.
- **FR-004**: Tras un inicio de sesión correcto, el sistema MUST conservar únicamente el acceso
  que concede Garmin (token), cifrado e identificado con la versión de la clave usada.
- **FR-005**: Cada cuenta Garmin vinculada MUST tener un identificador interno estable,
  independiente de su alias y de su correo de Garmin, y MUST conservarlo al reautenticar y al
  volver a vincularla tras una desvinculación con datos conservados.
- **FR-006**: El alias MUST tener entre 1 y 50 caracteres y ser único entre las cuentas del mismo
  usuario, sin distinguir mayúsculas.
- **FR-007**: Una misma cuenta Garmin (identificada por su identidad en Garmin, no por el correo
  escrito) MUST NOT tener más de una vinculación activa (en cualquier estado salvo "Desvinculada
  (datos conservados)"), ni con dos usuarios ni dos veces con el mismo. El rechazo MUST NOT
  revelar qué otro usuario la tiene vinculada. Una cuenta "Desvinculada (datos conservados)" no
  impide que otro usuario vincule esa cuenta Garmin: se crea una cuenta nueva con otro
  identificador interno, y los datos conservados siguen siendo del primer usuario.
- **FR-008**: Un usuario MUST poder tener como máximo 10 cuentas Garmin (configurable).
- **FR-009**: Los administradores MUST NOT poder vincular cuentas Garmin (feature 001, FR-004a).
- **FR-010**: Los intentos de vinculación y reautenticación fallidos de un usuario MUST limitarse
  a 5 cada 15 minutos (configurable), para no provocar bloqueos de Garmin.

**Aviso de datos y consentimiento de descarga**

- **FR-011**: Antes de vincular, el usuario MUST ver y aceptar un aviso que explique qué datos se
  descargarán (actividades, recorridos con GPS y datos de salud) y quién podría verlos (solo él y
  los entrenadores a los que dé consentimiento; nunca el administrador), y que puede desvincular
  y borrar cuando quiera.
- **FR-012**: El sistema MUST registrar la versión del aviso aceptada y la fecha, y MUST pedir de
  nuevo la aceptación cuando cambie la versión del aviso: se exige al vincular o reautenticar,
  y mientras el usuario no la acepte la página de inicio MUST mostrarle un aviso con enlace para
  hacerlo. Una versión nueva sin aceptar MUST NOT detener las descargas de las cuentas ya
  vinculadas.

**Listado y autorización**

- **FR-013**: El usuario MUST poder ver sus cuentas con alias, estado ("Válida", "Requiere
  reautenticación", "Error", "Desvinculada (datos conservados)" o "Borrando datos… (no se pudo
  completar)", este último con la acción "Reintentar" de FR-022), fecha del último login
  correcto en Garmin, fecha de la última sincronización ("Nunca" si no ha habido) y fecha de la
  última comprobación.
- **FR-014**: El sistema MUST mostrar y permitir gestionar a cada usuario solo sus propias
  cuentas. Cualquier acción sobre una cuenta por su identificador MUST responder igual que si no
  existiera cuando la cuenta no es del usuario.
- **FR-015**: El administrador MUST NOT tener acceso a las cuentas Garmin de los usuarios ni a sus
  datos desde la web.

**Estados y reautenticación**

- **FR-016**: Si Garmin deja de aceptar el acceso guardado de una cuenta (en una sincronización o
  una comprobación), la cuenta MUST pasar a "Requiere reautenticación" sin afectar a las demás
  cuentas del mismo usuario ni de otros.
- **FR-016a**: Mientras el usuario tenga alguna cuenta en "Requiere reautenticación" o "Error",
  la página de inicio MUST mostrarle un aviso con el alias de cada cuenta afectada y un enlace
  para resolverlo. El aviso desaparece cuando ninguna cuenta queda en esos estados. Esta feature
  no envía avisos por correo ni por otros canales externos.
- **FR-017**: Un fallo de otro tipo que impida usar la cuenta de forma persistente (por ejemplo,
  no poder descifrar su acceso) MUST dejarla en "Error" con un motivo comprensible. Los fallos
  transitorios (sin conexión, límite de peticiones) MUST NOT cambiar el estado de la cuenta.
- **FR-018**: El usuario MUST poder reautenticar una cuenta en cualquier estado salvo
  "Desvinculada" o con un borrado pendiente, con correo, contraseña y MFA si se pide. La reautenticación MUST rechazarse si la
  identidad en Garmin no coincide con la de la cuenta vinculada.
- **FR-019**: Una reautenticación correcta MUST reemplazar el acceso guardado, dejar la cuenta en
  "Válida" y conservar su identificador, su alias y sus datos.

**Desvinculación**

- **FR-020**: El usuario MUST poder desvincular una cuenta eligiendo de forma explícita entre
  "conservar datos" y "borrar datos", con una confirmación.
- **FR-021**: Desvincular MUST eliminar el acceso guardado de inmediato y detener cualquier
  descarga pendiente o futura de esa cuenta.
- **FR-022**: Con "borrar datos", el sistema MUST eliminar la cuenta, todos sus datos en la base
  de datos y todos sus ficheros crudos. El borrado MUST poder reanudarse si falla a mitad.
- **FR-023**: Con "conservar datos", los datos MUST seguir disponibles para el usuario y la cuenta
  MUST quedar "Desvinculada (datos conservados)". Los consentimientos dados a entrenadores sobre
  esa cuenta MUST seguir vigentes hasta que el usuario los revoque; la pantalla de desvinculación
  MUST avisarlo y ofrecer el borrado como alternativa. El usuario MUST poder borrar después esos datos
  o volver a vincular la misma cuenta Garmin recuperando su identificador interno.

**Comprobación**

- **FR-024**: El usuario MUST poder comprobar una cuenta, verificando con Garmin que el acceso
  guardado funciona, sin descargar datos. Se registra la fecha de la comprobación cuando Garmin da
  un resultado definitivo; si el acceso ya no vale, se aplica FR-016.
- **FR-025**: El sistema MUST limitar la comprobación a una por minuto y cuenta.

**Mensajes de error**

- **FR-026**: Los errores de Garmin MUST mostrarse con mensajes comprensibles y distintos para:
  credenciales incorrectas, código MFA incorrecto, intento MFA caducado, límite de peticiones de
  Garmin, bloqueo temporal de Garmin y falta de conexión. Ningún mensaje MUST incluir detalles
  técnicos, el contenido del acceso ni la contraseña.

**Arranque, auditoría y borrado del usuario**

- **FR-027**: La aplicación MUST negarse a arrancar si falta la clave maestra de cifrado de los
  accesos, nombrando el secreto que falta sin revelar ningún valor.
- **FR-028**: El sistema MUST registrar en la auditoría cada vinculación (correcta y fallida),
  reautenticación, desvinculación (indicando si se conservaron o borraron los datos), borrado de
  datos posterior, cambio de estado a "Requiere reautenticación" o "Error", comprobación y
  aceptación del aviso. Los eventos MUST NOT contener contraseñas, accesos, códigos MFA ni el
  correo de Garmin.
- **FR-028a**: El sistema MUST NOT guardar el correo de Garmin: lo usa solo durante el login
  (vinculación o reautenticación) y lo descarta igual que la contraseña. Para identificar la cuenta
  en Garmin (FR-007, FR-018) solo guarda el identificador que proporciona Garmin, que nunca se
  muestra ni se registra en logs. El usuario distingue sus cuentas por el alias.
- **FR-029**: El borrado de un usuario (feature 001, FR-028) MUST incluir todas sus cuentas
  Garmin, sus accesos, sus datos descargados y sus ficheros crudos.
- **FR-030**: La exportación de datos del usuario (feature 001, FR-023a) MUST incluir sus cuentas
  Garmin (alias, estado y fechas) y sus aceptaciones del aviso, y MUST NOT
  incluir los accesos guardados.

### Key Entities

- **Cuenta Garmin**: cuenta de Garmin Connect vinculada a un usuario. Atributos: identificador
  interno estable, usuario propietario, alias, identidad en Garmin (el identificador que da
  Garmin, para impedir duplicados; nunca el correo), estado (válida, requiere reautenticación,
  error, desvinculada con datos conservados o borrado pendiente de completar), motivo del último error, fechas de vinculación, último
  login correcto, última sincronización y última comprobación.
- **Acceso guardado (token)**: lo que Garmin concede tras el login. Se guarda solo cifrado, con
  la versión de la clave usada y la fecha de emisión; una cuenta tiene como máximo uno.
- **Intento de vinculación pendiente de MFA**: estado temporal de un login que espera el código
  MFA. Caduca a los 5 minutos y nunca contiene la contraseña de Garmin.
- **Aceptación del aviso de datos**: usuario, versión del aviso y fecha de aceptación.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un usuario vincula una cuenta, con o sin MFA, en menos de 1 minuto desde que abre
  el formulario (sin contar el tiempo de recibir el código MFA en su dispositivo).
- **SC-002**: Una revisión de la base de datos, los ficheros y los logs tras vincular,
  reautenticar, comprobar y desvincular cuentas no encuentra ninguna contraseña de Garmin, código
  MFA ni acceso en claro.
- **SC-003**: Con una cuenta en "Requiere reautenticación", el 100 % de las operaciones sobre las
  demás cuentas del mismo usuario siguen funcionando.
- **SC-004**: El 100 % de los intentos de ver o actuar sobre una cuenta ajena se rechazan con la
  misma respuesta que una cuenta inexistente.
- **SC-005**: Tras desvincular con "borrar datos", no queda ningún dato ni fichero crudo de esa
  cuenta.
- **SC-006**: El 100 % de las vinculaciones quedan precedidas de una aceptación registrada de la
  versión vigente del aviso.

## Assumptions

- Esta feature solo vincula y gestiona cuentas. La descarga de datos (actividades, salud) llega
  en features posteriores; hasta entonces la última sincronización se muestra como "Nunca". Los
  datos descargados y los ficheros crudos a los que se refieren la desvinculación y el borrado
  los introducirán esas features, que se engancharán al borrado de cuentas de esta.
- Solo los usuarios normales vinculan cuentas; un entrenador es un usuario normal que puede no
  tener ninguna. Los roles de club se definen en otra feature.
- La cuenta Garmin debe ser del propio usuario; la aplicación no puede verificarlo más allá de
  que el usuario conoce sus credenciales, y el aviso lo indica.
- El correo de Garmin no se guarda (FR-028a); el alias basta para que el usuario identifique
  cada cuenta. El identificador de Garmin se trata como dato personal (nunca en logs).
- El alias no se puede cambiar en esta feature; se podrá añadir más adelante.
- Para el límite de FR-010 cuentan como fallo los rechazos de Garmin a las credenciales o al
  código MFA. Los errores transitorios (conexión, límite de peticiones, bloqueo temporal) y los
  rechazos de la propia aplicación (alias, cuenta duplicada, máximo de cuentas) no cuentan.
- El máximo de 10 cuentas (FR-008) cuenta solo las cuentas vinculadas ("Válida", "Requiere
  reautenticación" o "Error"), no las "Desvinculadas (datos conservados)".
- La clave maestra de cifrado puede rotarse: los accesos cifrados con una versión anterior siguen
  pudiendo descifrarse mientras esa versión esté configurada.
- Los datos conservados de una cuenta desvinculada siguen visibles para los entrenadores con
  consentimiento vigente (FR-023); la feature de clubes y entrenadores debe tratarlos igual que
  los de una cuenta vinculada.
- La aplicación no ofrece en esta feature descargas automáticas ni manuales; "Comprobar" no
  descarga datos.
