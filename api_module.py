"""
API externa de solo lectura (`external-data-api`)
=================================================
Nuevo blueprint versionado bajo el prefijo `/api/v1` para consumo máquina a
máquina. Se autentica con `Token_API` (Bearer) en vez de la cookie de sesión
del navegador, de modo que una `Aplicación_Cliente` externa pueda recuperar
las tareas (de los tres módulos) y los eventos de calendario de un usuario.

Principio rector: **nada del comportamiento existente cambia**. Esta API vive
bajo su propio prefijo y su propio mecanismo de autenticación; los endpoints
`/api/...` basados en sesión quedan intactos.

Este módulo define, por ahora, la infraestructura compartida:

- `api_v1_bp`: el blueprint con `url_prefix="/api/v1"`.
- `TASK_MODULES`: mapa estático de clave de módulo a sus tablas
  `(tabla_tareas, tabla_subtareas)`.
- Ayudantes de serialización de tareas y subtareas con un formato de claves
  fijo y `null`/`[]` para campos y listas ausentes.

Los endpoints de lectura (`GET /api/v1/tasks`, `GET /api/v1/events`) y los
manejadores de error se añaden en tareas posteriores.
"""

import re

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import HTTPException

from auth import token_required
from database import get_connection

# Patrón estricto para el parámetro `?month`: exactamente `YYYY-MM`. La
# validación adicional del rango del mes (01–12) se hace tras el match.
_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# Mapa estático de clave de `Modulo_Tareas` a sus tablas correspondientes
# `(tabla_tareas, tabla_subtareas)`. Coincide con las tablas reales que crean
# las instancias de `create_tasks_module` en `app.py`.
TASK_MODULES = {
    "academic": ("tasks", "subtasks"),
    "work": ("work_tasks", "work_subtasks"),
    "personal": ("personal_tasks", "personal_subtasks"),
}


def serialize_subtask(row):
    """Serializa una `Subtarea` con las claves fijas `id`, `title`, `completed`.

    `completed` se normaliza del `0/1` de SQLite a un booleano `False/True`
    (Req 3.4). Acepta un `sqlite3.Row` o cualquier objeto indexable por clave.
    """
    return {
        "id": row["id"],
        "title": row["title"],
        "completed": bool(row["completed"]),
    }


def serialize_task(row, module, subtask_rows=None):
    """Serializa una `Tarea` con el conjunto de claves fijo del diseño.

    Las claves siempre presentes son, en este orden: `id`, `title`,
    `description`, `due_date`, `complexity`, `subject`, `created_at`, `module`
    y `subtasks` (Req 3.2). Los campos opcionales (`description`, `due_date`,
    `complexity`, `subject`) se emiten con valor `null` cuando no tienen valor
    almacenado, manteniendo la clave presente (Req 3.3).

    `module` es la clave del `Modulo_Tareas` al que pertenece la tarea
    (`academic`, `work` o `personal`). `subtask_rows` es un iterable de filas
    de subtareas ya ordenadas por `id ASC`; si es `None` o está vacío, la clave
    `subtasks` se emite como una lista vacía (Req 3.4, 3.5).
    """
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "due_date": row["due_date"],
        "complexity": row["complexity"],
        "subject": row["subject"],
        "created_at": row["created_at"],
        "module": module,
        "subtasks": [serialize_subtask(s) for s in (subtask_rows or [])],
    }


def serialize_event(row):
    """Serializa un `Evento` con el conjunto de claves fijo del diseño.

    Las claves, en este orden, son: `id`, `title`, `description`,
    `event_date`, `module` y `created_at` (Req 4.2). Acepta un `sqlite3.Row`
    o cualquier objeto indexable por clave.
    """
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "event_date": row["event_date"],
        "module": row["module"],
        "created_at": row["created_at"],
    }


@api_v1_bp.route("/tasks", methods=["GET"])
@token_required
def list_tasks():
    """Lista las `Tarea` del `Usuario_Propietario`, agregando los tres módulos.

    Autenticado por `Token_API` (`@token_required`); filtra siempre por
    `g.api_user["id"]`, de modo que sólo se devuelven tareas cuyo `user_id`
    coincide con el dueño del token (Req 3.1).

    El parámetro de consulta `?module` selecciona el `Modulo_Tareas`:

    - Ausente → se consultan los tres módulos (`academic`, `work`, `personal`)
      (Req 3.7).
    - Una clave válida → sólo ese módulo (Req 3.6).
    - Cualquier otro valor → 400 con `{"error": ...}` y sin devolver tareas
      (Req 3.9).

    Para cada módulo elegido se seleccionan las tareas del usuario y, por cada
    tarea, sus subtareas ordenadas por `id ASC` (Req 3.4). A cada tarea se le
    añade la clave `module`. La lista agregada se ordena por `created_at ASC`
    y, ante empate, por `id ASC` (Req 3.1). Si no hay coincidencias se devuelve
    una lista vacía (Req 3.8).
    """
    user_id = g.api_user["id"]

    module = request.args.get("module")
    if module is not None and module not in TASK_MODULES:
        return jsonify({"error": f"Módulo no válido: {module}"}), 400

    if module is None:
        modules = list(TASK_MODULES.keys())
    else:
        modules = [module]

    conn = get_connection()
    try:
        tasks = []
        for module_key in modules:
            tasks_table, subtasks_table = TASK_MODULES[module_key]
            task_rows = conn.execute(
                f"SELECT * FROM {tasks_table} WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            for task_row in task_rows:
                subtask_rows = conn.execute(
                    f"SELECT * FROM {subtasks_table} WHERE task_id = ? ORDER BY id ASC",
                    (task_row["id"],),
                ).fetchall()
                tasks.append(serialize_task(task_row, module_key, subtask_rows))
    finally:
        conn.close()

    tasks.sort(key=lambda t: (t["created_at"], t["id"]))

    return jsonify(tasks)


@api_v1_bp.route("/events", methods=["GET"])
@token_required
def list_events():
    """Lista los `Evento` de calendario del `Usuario_Propietario`.

    Autenticado por `Token_API` (`@token_required`); filtra siempre por
    `g.api_user["id"]`, de modo que sólo se devuelven eventos cuyo `user_id`
    coincide con el dueño del token (Req 4.1).

    El parámetro de consulta `?month` filtra por mes:

    - Ausente → se devuelven todos los eventos del usuario (Req 4.1).
    - Formato válido `YYYY-MM` (con mes 01–12) → sólo los eventos cuya
      `event_date` pertenece a ese mes (Req 4.4); lista vacía si no hay
      coincidencias (Req 4.5, 4.6).
    - Cualquier otro formato → 400 con `{"error": ...}` y sin devolver ningún
      evento (Req 4.7). La validación ocurre ANTES de tocar la base de datos.

    Los eventos se ordenan por `event_date ASC` y, ante empate, por `id ASC`
    (Req 4.3).
    """
    user_id = g.api_user["id"]

    month = request.args.get("month")
    if month is not None:
        if not _MONTH_PATTERN.match(month) or not (1 <= int(month[5:7]) <= 12):
            return (
                jsonify({"error": "El parámetro month debe tener formato YYYY-MM"}),
                400,
            )

    conn = get_connection()
    try:
        query = "SELECT * FROM events WHERE user_id = ?"
        params = [user_id]
        if month is not None:
            query += " AND event_date LIKE ?"
            params.append(f"{month}-%")
        query += " ORDER BY event_date ASC, id ASC"
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    return jsonify([serialize_event(r) for r in rows])


# ---------------------------------------------------------------------------
# Manejadores de error a nivel de blueprint
# ---------------------------------------------------------------------------
# Todos los errores de la API externa comparten el mismo sobre `{"error": ...}`
# con `Content-Type: application/json` (que `jsonify` fija automáticamente).
# Se registran con `api_v1_bp.errorhandler(...)` para que sólo capturen dentro
# del contexto de este blueprint; el 404 global de Flask (páginas HTML) y el
# resto del comportamiento de la app no cambian (Req 5.6).


@api_v1_bp.errorhandler(404)
def handle_not_found(error):
    """Devuelve 404 JSON para rutas/recursos inexistentes de la API externa.

    Responde con el sobre de error estándar `{"error": "Recurso no
    encontrado"}` y `Content-Type: application/json` (Req 5.4, 5.1).
    """
    return jsonify({"error": "Recurso no encontrado"}), 404


@api_v1_bp.errorhandler(Exception)
def handle_internal_error(error):
    """Devuelve 500 JSON ante un error de servidor inesperado.

    Los endpoints de esta API son de sólo lectura, de modo que un error
    durante una consulta no puede dejar datos a medias; se satisface así la
    cláusula de "no aplicar modificaciones" de Req 5.5. Responde con el sobre
    de error estándar `{"error": "Ocurrió un error interno del servidor"}` y
    `Content-Type: application/json` (Req 5.5, 5.1).

    Las `HTTPException` (p. ej. 400, 401, 404) se re-propagan para que las
    maneje su manejador específico y conserven su propio código de estado y
    cuerpo, en vez de convertirse en un 500 genérico.
    """
    if isinstance(error, HTTPException):
        return error
    return jsonify({"error": "Ocurrió un error interno del servidor"}), 500
