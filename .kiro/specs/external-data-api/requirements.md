# Requirements Document

## Introduction

Esta funcionalidad expone los datos de tareas y calendario de la aplicación TaskManager como una API JSON de solo lectura, pensada para que una **aplicación externa** (comunicación máquina a máquina) pueda recuperar la lista de tareas y los eventos del calendario de un usuario.

Hoy todos los endpoints `/api/` existentes están protegidos por la cookie de sesión del navegador (inicio de sesión vía `/login`), lo cual no sirve para una aplicación externa que no tiene navegador ni sesión. El núcleo de esta funcionalidad es un **mecanismo de autenticación por token de API** (en vez de la cookie de sesión) que permita a una aplicación externa identificarse como un usuario concreto y obtener únicamente los datos de ese usuario.

El alcance se centra en la **recuperación (lectura)** de datos:
- Tareas de los tres módulos existentes (académico, trabajo, personal), incluyendo sus subtareas.
- Eventos del calendario.

Respetando la propiedad de los datos por usuario (columna `user_id`) que ya existe en el esquema actual. La creación, edición y borrado de datos a través de esta API queda **fuera del alcance** de esta funcionalidad.

## Glossary

- **Sistema**: La aplicación TaskManager (servidor Flask) que atiende las peticiones.
- **API_Externa**: El conjunto de endpoints JSON de solo lectura definidos por esta funcionalidad para consumo máquina a máquina.
- **Aplicación_Cliente**: La aplicación externa que consume la API_Externa para recibir tareas y eventos.
- **Token_API**: Credencial secreta y opaca asociada a un usuario, que la Aplicación_Cliente presenta para autenticarse sin usar la cookie de sesión del navegador.
- **Usuario_Propietario**: El usuario (fila de la tabla `users`) al que pertenece un Token_API y cuyos datos puede recuperar ese token.
- **Tarea**: Registro de una de las tablas `tasks`, `work_tasks` o `personal_tasks`, con campos `id`, `title`, `description`, `due_date`, `complexity`, `subject`, `created_at`, `user_id`.
- **Subtarea**: Registro asociado a una Tarea (tablas `subtasks`, `work_subtasks`, `personal_subtasks`) con campos `id`, `task_id`, `title`, `completed`, `created_at`.
- **Modulo_Tareas**: Uno de los tres ámbitos de tareas existentes, identificado por la clave `academic`, `work` o `personal`.
- **Evento**: Registro de la tabla `events`, con campos `id`, `title`, `description`, `event_date`, `module`, `created_at`, `user_id`.
- **Encabezado_Autorizacion**: El encabezado HTTP `Authorization` de la petición, mediante el cual la Aplicación_Cliente envía el Token_API.

## Requirements

### Requisito 1: Autenticación por token de API

**Historia de Usuario:** Como desarrollador de una aplicación externa, quiero autenticarme mediante un token de API en lugar de la cookie de sesión del navegador, para que mi aplicación pueda acceder a los datos de forma programática.

#### Criterios de Aceptación

1. WHEN una petición a la API_Externa incluye un Token_API válido y no vacío en el Encabezado_Autorizacion bajo el esquema `Bearer <token>`, THE Sistema SHALL identificar al Usuario_Propietario asociado a ese Token_API y procesar la petición en nombre de ese usuario.
2. IF una petición a la API_Externa no incluye ningún Token_API, THEN THE Sistema SHALL responder con el código de estado HTTP 401 y un cuerpo JSON con un campo `error`, sin procesar ninguna operación sobre los datos del usuario.
3. IF una petición a la API_Externa incluye un Token_API que no corresponde a ningún Usuario_Propietario, THEN THE Sistema SHALL responder con el código de estado HTTP 401 y un cuerpo JSON con un campo `error`, sin procesar ninguna operación sobre los datos del usuario.
4. THE Sistema SHALL almacenar cada Token_API en la base de datos de forma que el valor en claro no sea recuperable a partir del registro almacenado.
5. WHEN el Sistema recibe el Encabezado_Autorizacion, THE Sistema SHALL aceptar únicamente el esquema `Bearer <token>` con un token no vacío como formato válido.
6. IF una petición a la API_Externa incluye un Encabezado_Autorizacion con un formato distinto de `Bearer <token>` no vacío, THEN THE Sistema SHALL responder con el código de estado HTTP 401 y un cuerpo JSON con un campo `error`, sin procesar ninguna operación sobre los datos del usuario.

### Requisito 2: Emisión de tokens de API

**Historia de Usuario:** Como usuario propietario de una cuenta, quiero generar un token de API para mi cuenta, para que pueda entregárselo a la aplicación externa que consumirá mis datos.

#### Criterios de Aceptación

1. WHEN un Usuario_Propietario autenticado por sesión solicita la emisión de un Token_API, THE Sistema SHALL generar un Token_API aleatorio de entre 32 y 128 caracteres, asociarlo a ese Usuario_Propietario y devolver el valor en claro exactamente una vez en la respuesta de esa solicitud.
2. WHEN un Usuario_Propietario intenta recuperar o visualizar el valor en claro de un Token_API después de la respuesta de emisión inicial, THE Sistema SHALL rechazar la solicitud sin devolver el valor en claro e indicar que el token solo se muestra una vez en el momento de su emisión.
3. IF un Usuario_Propietario que ya tiene un Token_API activo solicita la emisión de un nuevo Token_API, THEN THE Sistema SHALL generar un nuevo Token_API, invalidar el Token_API anterior en la misma operación de manera que cualquier uso posterior del anterior sea rechazado, y devolver el nuevo valor en claro exactamente una vez.
4. WHEN un Usuario_Propietario autenticado por sesión solicita revocar su Token_API activo, THE Sistema SHALL invalidar ese Token_API de manera que su uso posterior sea rechazado con el código de estado HTTP 401.
5. IF una solicitud de emisión o de revocación de Token_API se recibe sin una sesión autenticada de Usuario_Propietario, THEN THE Sistema SHALL rechazar la solicitud sin generar, devolver ni modificar ningún Token_API, e indicar en la respuesta que se requiere autenticación.
6. IF un Usuario_Propietario solicita revocar un Token_API cuando no tiene ningún Token_API activo, THEN THE Sistema SHALL rechazar la solicitud sin modificar el estado de ningún token e indicar en la respuesta que no existe un token activo para revocar.
7. IF falla la generación o el almacenamiento de un Token_API durante una solicitud de emisión, THEN THE Sistema SHALL no asociar ningún Token_API al Usuario_Propietario, mantener sin cambios cualquier Token_API existente previo, e indicar en la respuesta un error de emisión.
8. THE Sistema SHALL asociar cada Token_API a exactamente un Usuario_Propietario.

### Requisito 3: Recuperación de la lista de tareas

**Historia de Usuario:** Como aplicación externa, quiero recuperar la lista de tareas del usuario en formato JSON, para que pueda mostrarlas o procesarlas en mi propia aplicación.

#### Criterios de Aceptación

1. WHEN la API_Externa recibe una petición autenticada de lista de tareas, THE Sistema SHALL devolver en formato JSON únicamente las Tareas cuyo `user_id` coincide con el Usuario_Propietario del Token_API, ordenadas de forma ascendente por el campo `created_at` y, ante valores iguales de `created_at`, de forma ascendente por el campo `id`.
2. WHEN la API_Externa devuelve una Tarea, THE Sistema SHALL incluir los campos `id`, `title`, `description`, `due_date`, `complexity`, `subject`, `created_at` y la clave del Modulo_Tareas (`academic`, `work` o `personal`) al que pertenece.
3. IF un campo opcional de una Tarea devuelta (`description`, `due_date`, `subject` o `complexity`) no tiene valor almacenado, THEN THE Sistema SHALL incluir dicho campo en el JSON con valor nulo, manteniendo la clave presente.
4. WHEN la API_Externa devuelve una Tarea, THE Sistema SHALL incluir la lista de Subtareas asociadas a esa Tarea con los campos `id`, `title` y `completed`, ordenadas de forma ascendente por el campo `id`.
5. IF una Tarea devuelta no tiene Subtareas asociadas, THEN THE Sistema SHALL incluir la clave de la lista de Subtareas con una lista vacía.
6. WHERE la petición de lista de tareas especifica un Modulo_Tareas válido (`academic`, `work` o `personal`), THE Sistema SHALL devolver únicamente las Tareas de ese Modulo_Tareas.
7. WHERE la petición de lista de tareas no especifica ningún Modulo_Tareas, THE Sistema SHALL devolver las Tareas de los tres módulos (`academic`, `work` y `personal`).
8. IF la petición autenticada de lista de tareas no encuentra ninguna Tarea que cumpla los criterios de filtrado, THEN THE Sistema SHALL devolver un JSON con una lista de Tareas vacía.
9. IF la petición de lista de tareas especifica un Modulo_Tareas que no es `academic`, `work` ni `personal`, THEN THE Sistema SHALL responder con el código de estado HTTP 400 y un cuerpo JSON con un campo `error` cuyo valor indique que el módulo especificado no es válido, sin devolver ninguna Tarea.

### Requisito 4: Recuperación del calendario

**Historia de Usuario:** Como aplicación externa, quiero recuperar los eventos del calendario del usuario en formato JSON, para que pueda mostrarlos junto a las tareas en mi propia aplicación.

#### Criterios de Aceptación

1. WHEN la API_Externa recibe una petición autenticada de eventos de calendario, THE Sistema SHALL devolver en formato JSON únicamente los Eventos cuyo `user_id` coincide con el Usuario_Propietario del Token_API.
2. WHEN la API_Externa devuelve un Evento, THE Sistema SHALL incluir los campos `id`, `title`, `description`, `event_date`, `module` y `created_at`.
3. THE Sistema SHALL devolver los Eventos ordenados de forma ascendente por `event_date` y, ante valores iguales de `event_date`, de forma ascendente por `id`.
4. WHERE la petición de eventos especifica un mes en formato `YYYY-MM`, THE Sistema SHALL devolver únicamente los Eventos cuya `event_date` pertenece a ese mes.
5. IF la petición de eventos especifica un mes con formato `YYYY-MM` válido para el que no existen Eventos, THEN THE Sistema SHALL devolver un JSON con una lista de Eventos vacía.
6. IF la petición autenticada de eventos no encuentra ningún Evento que cumpla los criterios de filtrado, THEN THE Sistema SHALL devolver un JSON con una lista de Eventos vacía.
7. IF la petición de eventos especifica un mes con un formato distinto de `YYYY-MM`, THEN THE Sistema SHALL responder con el código de estado HTTP 400 y un cuerpo JSON con un campo `error`, sin devolver ningún Evento.

### Requisito 5: Formato y consistencia de las respuestas

**Historia de Usuario:** Como aplicación externa, quiero que las respuestas tengan un formato JSON consistente y predecible, para que pueda procesarlas de forma fiable.

#### Criterios de Aceptación

1. WHEN la API_Externa responde a cualquier petición, THE Sistema SHALL fijar el encabezado HTTP `Content-Type` con el valor `application/json`.
2. WHEN la API_Externa responde correctamente a una petición de recuperación de una colección, THE Sistema SHALL devolver el código de estado HTTP 200 y un cuerpo JSON cuyo elemento raíz es una lista que contiene un elemento por cada recurso de la colección solicitada.
3. WHEN la API_Externa responde correctamente a una petición de recuperación de una colección que no contiene recursos, THE Sistema SHALL devolver el código de estado HTTP 200 y un cuerpo JSON cuyo elemento raíz es una lista vacía.
4. IF la API_Externa recibe una petición de un recurso o ruta que no existe, THEN THE Sistema SHALL responder con el código de estado HTTP 404 y un cuerpo JSON que incluye un campo `error` con una descripción legible que indica que el recurso no fue encontrado.
5. IF la API_Externa procesa una petición y ocurre un error de servidor inesperado, THEN THE Sistema SHALL responder con el código de estado HTTP 500, un cuerpo JSON que incluye un campo `error` con una descripción legible que indica que ocurrió un error de servidor, y SHALL no aplicar ninguna modificación de datos derivada de esa petición.
6. THE Sistema SHALL mantener los endpoints existentes basados en sesión de forma que, para peticiones idénticas, devuelvan el mismo código de estado HTTP, el mismo tipo de contenido y el mismo cuerpo de respuesta que antes de introducir la API_Externa.
