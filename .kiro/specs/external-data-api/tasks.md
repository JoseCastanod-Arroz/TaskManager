# Implementation Plan: external-data-api

## Overview

Este plan convierte el diseño de la API JSON de solo lectura (`external-data-api`) en pasos de código incrementales. El orden respeta el principio rector del diseño: **nada del comportamiento existente cambia**. Primero se prepara el entorno de pruebas y el esquema (`api_tokens`), luego los ayudantes de token en `auth.py`, después los endpoints de emisión/revocación por sesión, a continuación el nuevo blueprint `api_v1_bp` con los endpoints de lectura y sus manejadores de error, y finalmente el cableado en `app.py`. Cada paso se apoya en el anterior y termina integrado; las pruebas se ubican junto a la implementación que validan.

La implementación es en **Python/Flask** (lenguaje del proyecto y del diseño). Las pruebas basadas en propiedades usan **Hypothesis** (mínimo 100 ejemplos por prueba), con una prueba por cada una de las 15 propiedades de corrección. Los requisitos no cubiertos por propiedades (2.2, 2.5, 2.6, 2.7, 5.4, 5.5, 5.6) se validan con pruebas de ejemplo/integración.

## Tasks

- [x] 1. Configurar el entorno de pruebas (pytest + Hypothesis)
  - [x] 1.1 Instalar y estructurar el entorno de pruebas
    - Añadir `pytest` y `hypothesis` como dependencias de desarrollo (por ejemplo, en `requirements-dev.txt` o `requirements.txt`).
    - Crear el directorio `tests/` con `__init__.py` y un `conftest.py` con utilidades compartidas: crear una base SQLite en memoria/temporal, invocar `init_auth_db`, `init_api_tokens_db` y los `init_db` de los tres módulos, y una fixture de cliente de pruebas Flask.
    - Añadir estrategias base de Hypothesis reutilizables (generadores de usuarios, tareas, subtareas y eventos) en un módulo de ayuda de tests para reusar en las pruebas de propiedad.
    - _Requisitos: soporte de la estrategia de pruebas del diseño (Testing Strategy)_

- [x] 2. Crear la tabla `api_tokens` y los ayudantes de hashing/resolución en `auth.py`
  - [x] 2.1 Implementar `init_api_tokens_db()` y `_hash_token(raw_token)`
    - Crear `init_api_tokens_db()` que ejecute el `CREATE TABLE IF NOT EXISTS api_tokens` con `user_id UNIQUE`, `token_hash TEXT NOT NULL UNIQUE`, `created_at` y `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE`.
    - Implementar `_hash_token(raw_token: str) -> str` devolviendo el SHA-256 hex determinista.
    - _Requisitos: 1.4, 2.8_

  - [x] 2.2 Implementar `generate_api_token(user_id)` con rotación atómica
    - Generar `raw = secrets.token_urlsafe(32)`, calcular su hash y, en una única transacción, borrar cualquier token previo del usuario e insertar el nuevo `(user_id, token_hash, created_at)`.
    - Ante excepción hacer `rollback` y propagar el error sin dejar estado a medias; devolver el valor en claro `raw` al llamador.
    - _Requisitos: 2.1, 2.3, 2.7, 2.8_

  - [x]* 2.3 Escribir prueba de propiedad para la longitud del token
    - **Property 2: Longitud del token emitido**
    - **Valida: Requisitos 2.1**
    - Etiqueta: `# Feature: external-data-api, Property 2: ...`; `@settings(max_examples=100)`.

  - [x]* 2.4 Escribir prueba de propiedad para la no recuperabilidad del claro
    - **Property 4: El valor en claro del token no es recuperable del registro**
    - **Valida: Requisitos 1.4**
    - Verifica que ninguna columna contiene el claro y que `token_hash == _hash_token(raw)` y `token_hash != raw`.

  - [x] 2.5 Implementar `revoke_api_token(user_id)`
    - Borrar la fila de `api_tokens` del usuario; devolver `True` si existía y `False` si no había ninguno.
    - _Requisitos: 2.4, 2.6_

  - [x] 2.6 Implementar `resolve_token_user(auth_header)` y el decorador `token_required`
    - Función pura: retorna `None` si el header es `None`, no empieza por `Bearer `, o el token está vacío/solo espacios, o si el hash no coincide con ningún registro; en coincidencia hace `JOIN` con `users` y retorna `{id, username}`.
    - Decorador `token_required`: si `resolve_token_user` retorna `None`, responde 401 JSON `{"error": ...}`; en éxito guarda el usuario en `flask.g.api_user` y ejecuta la vista.
    - _Requisitos: 1.1, 1.2, 1.3, 1.5, 1.6_

  - [x]* 2.7 Escribir prueba de propiedad para el round-trip emisión→resolución
    - **Property 1: Round-trip de emisión y aceptación del token**
    - **Valida: Requisitos 1.1, 1.5, 2.1, 2.8**

  - [x]* 2.8 Escribir prueba de propiedad para el rechazo de credenciales inválidas
    - **Property 3: Rechazo de credenciales inválidas**
    - **Valida: Requisitos 1.2, 1.3, 1.6**
    - Generar headers mal formados (ausente, esquema distinto, `Bearer` vacío/espacios) y tokens inexistentes; esperar 401 con `error`.

  - [x]* 2.9 Escribir prueba de propiedad para la rotación de tokens
    - **Property 5: La rotación invalida el token anterior**
    - **Valida: Requisitos 2.3, 2.8**

  - [x]* 2.10 Escribir prueba de propiedad para la revocación de tokens
    - **Property 6: La revocación invalida el token**
    - **Valida: Requisitos 2.4**

- [x] 3. Checkpoint - Asegurar que todas las pruebas de tokens pasan
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implementar los endpoints de emisión/revocación en `auth_bp` (protegidos por sesión)
  - [x] 4.1 Implementar `POST /api/token` y `DELETE /api/token`
    - `POST /api/token` con `@api_login_required`: llama a `generate_api_token(session_user_id)` y devuelve `{"token": "<claro>"}` una sola vez; ante fallo de generación/almacenamiento devuelve 500 con `error` sin modificar el token previo.
    - `DELETE /api/token` con `@api_login_required`: llama a `revoke_api_token`; si no había token activo devuelve 404 con `error`, si lo había devuelve una respuesta de éxito.
    - No exponer ningún endpoint que devuelva el claro tras la emisión.
    - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x]* 4.2 Escribir pruebas de ejemplo/integración de emisión y revocación
    - Emisión sin sesión → 401; revocación sin sesión → 401 (Req 2.5).
    - Revocar sin token activo → 404 con `error` (Req 2.6).
    - No existe endpoint que devuelva el token en claro tras la emisión (Req 2.2).
    - Fallo de almacenamiento simulado con `mock` durante la emisión → 500 y token previo intacto (Req 2.7).
    - _Requisitos: 2.2, 2.5, 2.6, 2.7_

- [x] 5. Crear `api_module.py` con el blueprint `api_v1_bp` y el endpoint de tareas
  - [x] 5.1 Crear `api_v1_bp` y el mapa `TASK_MODULES`, con serialización de tareas/subtareas
    - Definir `api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")` y el mapa `TASK_MODULES = {"academic": ("tasks","subtasks"), "work": (...), "personal": (...)}`.
    - Escribir ayudantes de serialización: tarea con claves fijas `id, title, description, due_date, complexity, subject, created_at, module, subtasks` (opcionales ausentes como `null`); subtareas con `id, title, completed` (normalizando 0/1 a booleano) y `[]` si no hay.
    - _Requisitos: 3.2, 3.3, 3.4, 3.5_

  - [x] 5.2 Implementar `GET /api/v1/tasks` con agregación, filtro y orden
    - Aplicar `@token_required`; filtrar por `g.api_user["id"]`.
    - `?module` válido → solo ese módulo; ausente → los tres; inválido → 400 con `error` sin devolver tareas.
    - Para cada módulo elegido, `SELECT` de tareas del usuario y sus subtareas (`ORDER BY id ASC`), añadir clave `module`, concatenar y ordenar la lista agregada por `created_at ASC` y empate por `id ASC`; lista vacía si no hay coincidencias.
    - _Requisitos: 3.1, 3.6, 3.7, 3.8, 3.9_

  - [x]* 5.3 Escribir prueba de propiedad de aislamiento y orden de tareas
    - **Property 7: Aislamiento y orden de las tareas por propietario**
    - **Valida: Requisitos 3.1, 5.2**

  - [x]* 5.4 Escribir prueba de propiedad de serialización completa con opcionales nulos
    - **Property 8: Serialización completa de la tarea con opcionales nulos**
    - **Valida: Requisitos 3.2, 3.3**

  - [x]* 5.5 Escribir prueba de propiedad de inclusión y orden de subtareas
    - **Property 9: Inclusión y orden de subtareas**
    - **Valida: Requisitos 3.4, 3.5**

  - [x]* 5.6 Escribir prueba de propiedad de filtrado por módulo
    - **Property 10: Filtrado de tareas por módulo**
    - **Valida: Requisitos 3.6, 3.7**

  - [x]* 5.7 Escribir prueba de propiedad de módulo no válido
    - **Property 11: Módulo de tareas no válido**
    - **Valida: Requisitos 3.9**

- [x] 6. Implementar `GET /api/v1/events` en `api_v1_bp`
  - [x] 6.1 Implementar el endpoint de eventos con validación de mes, filtro y orden
    - Aplicar `@token_required`; filtrar por `g.api_user["id"]`; serializar con claves `id, title, description, event_date, module, created_at`.
    - Validar `?month` con patrón estricto `^\d{4}-\d{2}$` y mes 01–12 antes de tocar la base; formato inválido → 400 con `error` sin devolver eventos.
    - `month` válido → solo eventos de ese mes; ordenar por `event_date ASC` y empate por `id ASC`; lista vacía si no hay coincidencias.
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x]* 6.2 Escribir prueba de propiedad de aislamiento, serialización y orden de eventos
    - **Property 12: Aislamiento, serialización y orden de los eventos**
    - **Valida: Requisitos 4.1, 4.2, 4.3, 5.2**

  - [x]* 6.3 Escribir prueba de propiedad de filtrado de eventos por mes
    - **Property 13: Filtrado de eventos por mes**
    - **Valida: Requisitos 4.4**

  - [x]* 6.4 Escribir prueba de propiedad de mes con formato no válido
    - **Property 14: Mes con formato no válido**
    - **Valida: Requisitos 4.7**

- [x] 7. Implementar los manejadores de error a nivel de blueprint y el sobre de respuesta
  - [x] 7.1 Registrar manejadores 404/500 y garantizar `Content-Type: application/json`
    - `@api_v1_bp.errorhandler(404)` → 404 `{"error": "Recurso no encontrado"}` (Req 5.4).
    - `@api_v1_bp.errorhandler(Exception)` (500) → 500 `{"error": "Ocurrió un error interno del servidor"}` sin aplicar modificaciones de datos (Req 5.5).
    - Asegurar que todas las respuestas de la API externa (éxito y error) llevan `Content-Type: application/json` y que las colecciones exitosas devuelven 200 con lista raíz.
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x]* 7.2 Escribir prueba de propiedad de Content-Type y forma de la colección
    - **Property 15: Content-Type y forma de la colección**
    - **Valida: Requisitos 5.1, 5.2, 5.3**

  - [x]* 7.3 Escribir pruebas de ejemplo/integración de rutas y errores de servidor
    - Ruta inexistente `/api/v1/...` → 404 con `error` (Req 5.4).
    - Error inesperado simulado con `mock` que lanza en la consulta → 500 con `error` (Req 5.5).
    - _Requisitos: 5.4, 5.5_

- [x] 8. Cablear el nuevo blueprint y la inicialización en `app.py`
  - [x] 8.1 Registrar `api_v1_bp` e invocar `init_api_tokens_db()`
    - Importar y `app.register_blueprint(api_v1_bp)` sin alterar el resto del registro.
    - En `__main__`, llamar `init_api_tokens_db()` después de `init_auth_db()` (dependencia de la clave foránea a `users`), junto a las demás inicializaciones.
    - _Requisitos: 5.6_

  - [x]* 8.2 Escribir prueba de regresión de compatibilidad de los endpoints de sesión
    - Para peticiones idénticas con sesión, `/api/tasks`, `/api/work-tasks`, `/api/personal-tasks` y `/api/events` devuelven el mismo código de estado, `Content-Type` y cuerpo que antes de introducir la API externa.
    - _Requisitos: 5.6_

- [x] 9. Checkpoint final - Asegurar que todas las pruebas pasan
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las subtareas marcadas con `*` son opcionales (pruebas) y pueden omitirse para un MVP más rápido; las tareas de implementación núcleo nunca son opcionales.
- Cada tarea referencia requisitos concretos para trazabilidad, y cada prueba de propiedad referencia su propiedad del diseño.
- Las pruebas de propiedad usan Hypothesis con `@settings(max_examples=100)` (mínimo 100 ejemplos) y el comentario de etiqueta `# Feature: external-data-api, Property {n}: {texto}`.
- Existe exactamente una prueba de propiedad por cada una de las 15 propiedades de corrección del diseño.
- Los requisitos no cubiertos por propiedades (2.2, 2.5, 2.6, 2.7, 5.4, 5.5, 5.6) se cubren con las pruebas de ejemplo/integración de las tareas 4.2, 7.3 y 8.2.
- Los checkpoints garantizan validación incremental.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.5", "2.6"] },
    { "id": 3, "tasks": ["2.3", "2.4", "2.7", "2.8", "2.9", "2.10", "4.1"] },
    { "id": 4, "tasks": ["4.2", "5.1"] },
    { "id": 5, "tasks": ["5.2", "6.1"] },
    { "id": 6, "tasks": ["5.3", "5.4", "5.5", "5.6", "5.7", "6.2", "6.3", "6.4", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 8, "tasks": ["8.2"] }
  ]
}
```
