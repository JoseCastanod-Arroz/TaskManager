"""
Módulo de Línea del día (Line of task)
======================================
Nueva sección autónoma del gestor de tareas: el usuario arma la lista
ordenada de actividades de su día **eligiendo tareas que ya existen** en
los tres módulos de tareas (`tasks` → académico, `work_tasks` → trabajo,
`personal_tasks` → personal). La sección nunca crea, edita ni elimina las
tareas subyacentes: sólo las *referencia* y las *ordena*.

Sigue la arquitectura de `calendar_module.py`: un blueprint con guardia de
sesión (`before_request`), un `init_db()` que crea sus propias tablas vía
`database.get_connection()`, una página HTML y una API JSON bajo `/api/...`.
Se conecta a la app principal con una sola línea (`app.register_blueprint`)
y no toca el esquema de las tablas de tareas existentes (NFR-03).

La "naturaleza" de una tarea (académica, trabajo o personal) se **deriva** de
la cadena `module` guardada en el ítem de línea; no se añade ningún campo a
las tablas de tareas (FR-01).

Este archivo define, por ahora, la infraestructura compartida:

- `line_bp`: el blueprint del módulo.
- `MODULE_LABELS` / `VALID_MODULES`: etiquetas de naturaleza y conjunto de
  módulos válidos.
- `TASK_MODULES`: mapa estático de clave de módulo a sus tablas
  `(tabla_tareas, tabla_subtareas)` (coincide con `api_module.TASK_MODULES`).
- `line_bp.init_db()`: crea las tablas `line` y `line_items`.

La guardia de sesión, los ayudantes de lógica y los endpoints se añaden en
tareas posteriores sobre este mismo archivo.
"""

from flask import Blueprint, jsonify, request, render_template, redirect, url_for, session
from database import get_connection
from nav import NAV_LINKS

line_bp = Blueprint("line", __name__)


# ---------- Autenticación ----------
# Igual que los módulos de tareas/calendario: la página redirige al login y la
# API responde 401 cuando no hay sesión activa (NFR-02).
@line_bp.before_request
def require_login():
    if session.get("user_id") is not None:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "No autorizado"}), 401
    return redirect(url_for("auth.login", next=request.path))

# Etiquetas de "naturaleza" derivadas del `module` de cada ítem de línea
# (FR-01). A diferencia del calendario, la línea sólo admite los tres módulos
# de tareas reales; no hay un valor "general".
MODULE_LABELS = {
    "academic": "Académico",
    "work": "Trabajo",
    "personal": "Personal",
}
VALID_MODULES = set(MODULE_LABELS)

# Mapa estático de clave de módulo a sus tablas correspondientes
# `(tabla_tareas, tabla_subtareas)`. Coincide con `api_module.TASK_MODULES` y
# con las tablas reales que crean las instancias de `create_tasks_module` en
# `app.py`.
TASK_MODULES = {
    "academic": ("tasks", "subtasks"),
    "work": ("work_tasks", "work_subtasks"),
    "personal": ("personal_tasks", "personal_subtasks"),
}


# ---------- Página ----------
# Igual que `calendar_module.calendar_page`: renderiza la plantilla de la
# sección pasando la barra de navegación compartida (`NAV_LINKS`) y las
# etiquetas de naturaleza (`MODULE_LABELS`). La guardia `before_request`
# redirige al login cuando no hay sesión (NFR-01/NFR-02).
@line_bp.route("/linea")
def line_page():
    return render_template("line.html", nav_links=NAV_LINKS, module_labels=MODULE_LABELS)


def init_db():
    """Crea las tablas `line` y `line_items` si aún no existen.

    `line` guarda una sola línea por usuario (`user_id UNIQUE`, FK a `users`
    con borrado en cascada). `line_items` guarda cada referencia a una tarea
    por el par `(module, task_id)` más su `position` dentro de la línea, con
    FK a `line` (cascada) y `UNIQUE(line_id, module, task_id)` para que una
    tarea aparezca a lo sumo una vez.

    No se declara ninguna FK de `line_items` hacia las tablas de tareas: la
    tabla destino se elige en tiempo de ejecución según `module`, algo que
    SQLite no puede expresar como FK declarativa. La integridad referencial
    (FR-11) se garantiza en el código de la aplicación (`sweep_dangling`).

    No modifica el esquema de las tablas de tareas existentes (NFR-03).
    """
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS line (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS line_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            line_id    INTEGER NOT NULL,
            module     TEXT    NOT NULL,
            task_id    INTEGER NOT NULL,
            position   INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (line_id) REFERENCES line (id) ON DELETE CASCADE,
            UNIQUE (line_id, module, task_id)
        )
    """)
    conn.commit()
    conn.close()


# Expuesto como atributo del blueprint para que `app.py` lo invoque igual que
# el resto de módulos (p. ej. `calendar_bp.init_calendar_db`).
line_bp.init_db = init_db


# ---------- Lógica central de la línea ----------
def get_or_create_line(conn, user_id):
    """Devuelve el id de la única línea del usuario, creándola si no existe.

    Hay a lo sumo una línea por usuario (`line.user_id` es `UNIQUE`). Si ya
    existe una fila para `user_id` se devuelve su `id`; en caso contrario se
    inserta la fila de línea y se devuelve el `id` recién creado. La escritura
    se confirma (`commit`) para que la línea quede disponible en conexiones
    posteriores (cada operación de la app abre y cierra su propia conexión).

    No crea ni modifica ninguna tarea: sólo asegura que exista el contenedor
    de línea del usuario.
    """
    row = conn.execute(
        "SELECT id FROM line WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is not None:
        return row["id"]

    cur = conn.execute(
        "INSERT INTO line (user_id) VALUES (?)",
        (user_id,),
    )
    conn.commit()
    return cur.lastrowid


def task_exists(conn, module, task_id, user_id):
    """Indica si `(module, task_id)` es una tarea del usuario en ese módulo.

    Devuelve `True` sólo cuando existe una tarea con `id == task_id` y
    `user_id == user_id` en la tabla de tareas correspondiente a `module`
    (según `TASK_MODULES`). Esto reproduce el patrón de aislamiento por usuario
    del resto de la app (p. ej. `WHERE id = ? AND user_id = ?`), de modo que
    nunca reporta como existente la tarea de otro usuario.

    Un `module` que no esté en `TASK_MODULES` (ausente o no válido) devuelve
    `False` sin tocar la base de datos.
    """
    tables = TASK_MODULES.get(module)
    if tables is None:
        return False

    tasks_table = tables[0]
    row = conn.execute(
        f"SELECT 1 FROM {tasks_table} WHERE id = ? AND user_id = ?",
        (task_id, user_id),
    ).fetchone()
    return row is not None

def sweep_dangling(conn, line_id):
    """Elimina los `line_items` cuya tarea destino ya no existe y cuenta cuántos.

    Un ítem de línea referencia una tarea por el par `(module, task_id)`, sin
    clave foránea declarativa (la tabla destino depende de `module` en tiempo
    de ejecución). Este barrido perezoso recorre los ítems de la línea y, para
    cada uno, comprueba si sigue existiendo una fila con `id == task_id` en la
    tabla de tareas correspondiente a `module` (según `TASK_MODULES`).

    Se considera "colgante" (y se borra) todo ítem cuyo `module` no sea válido
    o cuyo `(module, task_id)` ya no apunte a ninguna tarea existente. Así se
    satisface FR-11: cuando una tarea referenciada se elimina, su ítem de línea
    desaparece en la siguiente lectura.

    La comprobación de existencia NO filtra por `user_id`: la propiedad de la
    tarea ya se validó al añadir el ítem (`task_exists`), y la línea en sí está
    aislada por usuario; aquí sólo interesa si la fila destino sigue presente.

    Devuelve el número de ítems eliminados. La escritura se confirma con
    `commit` para que el barrido quede persistido.
    """
    rows = conn.execute(
        "SELECT id, module, task_id FROM line_items WHERE line_id = ?",
        (line_id,),
    ).fetchall()

    dangling_ids = []
    for row in rows:
        tables = TASK_MODULES.get(row["module"])
        if tables is None:
            dangling_ids.append(row["id"])
            continue
        tasks_table = tables[0]
        target = conn.execute(
            f"SELECT 1 FROM {tasks_table} WHERE id = ?",
            (row["task_id"],),
        ).fetchone()
        if target is None:
            dangling_ids.append(row["id"])

    for item_id in dangling_ids:
        conn.execute("DELETE FROM line_items WHERE id = ?", (item_id,))

    if dangling_ids:
        conn.commit()

    return len(dangling_ids)


def _serialize_subtask(row):
    """Serializa una subtarea con las claves fijas `id`, `title`, `completed`.

    `completed` se normaliza del `0/1` de SQLite a un booleano, igual que la
    convención del API externa (`api_module.serialize_subtask`).
    """
    return {
        "id": row["id"],
        "title": row["title"],
        "completed": bool(row["completed"]),
    }


def _serialize_task(row, subtask_rows):
    """Serializa la tarea referenciada por un ítem de línea.

    Reproduce las convenciones de serialización del API externa
    (`api_module.serialize_task`): las claves opcionales (`description`,
    `due_date`, `complexity`, `subject`) se emiten con su valor almacenado
    (posiblemente `null`) manteniendo la clave presente, y `subtasks` es
    siempre una lista (vacía cuando la tarea no tiene subtareas), ordenada por
    `id ASC` por quien provee `subtask_rows`.
    """
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "due_date": row["due_date"],
        "complexity": row["complexity"],
        "subject": row["subject"],
        "created_at": row["created_at"],
        "subtasks": [_serialize_subtask(s) for s in subtask_rows],
    }


def resolve_line(conn, user_id):
    """Devuelve la línea del usuario, ordenada y ya barrida de referencias rotas.

    Flujo:

    1. Obtiene (o crea) la única línea del usuario con `get_or_create_line`.
    2. Barre los ítems colgantes con `sweep_dangling` (FR-11), de modo que el
       resultado nunca incluya una tarea inexistente.
    3. Selecciona los ítems restantes ordenados por `position ASC` y, por cada
       uno, resuelve su tarea subyacente y sus subtareas (ordenadas por
       `id ASC`, lista siempre presente — FR-09/Req 1.9).

    Cada elemento devuelto tiene la forma serializada del diseño::

        {
          "item_id": <id del line_item>,
          "module": "work",
          "nature": "Trabajo",            # derivada de `module` vía MODULE_LABELS
          "position": 0,
          "task": { ...campos de la tarea..., "subtasks": [...] }
        }

    `nature` se deriva exclusivamente de `module` (FR-01); ningún campo de la
    tarea influye en ella. Como el barrido ya eliminó los módulos no válidos,
    todo ítem resuelto tiene un `module` presente en `TASK_MODULES`.
    """
    line_id = get_or_create_line(conn, user_id)
    removed = sweep_dangling(conn, line_id)
    # El barrido perezoso es una forma de baja (FR-11): si eliminó algún ítem,
    # las posiciones supervivientes pueden quedar con huecos (p. ej. [0, 1] con
    # el de posición 1 borrado deja un único ítem en posición 1). Renumeramos a
    # una secuencia contigua 0..n-1 (Propiedad de Corrección 5 / FR-07) antes de
    # seleccionar y serializar. Sólo escribimos cuando hubo bajas, para no tocar
    # la base de datos en la ruta de lectura habitual (sin ítems colgantes).
    if removed > 0:
        normalize_positions(conn, line_id)
        conn.commit()

    item_rows = conn.execute(
        """SELECT id, module, task_id, position
           FROM line_items
           WHERE line_id = ?
           ORDER BY position ASC""",
        (line_id,),
    ).fetchall()

    resolved = []
    for item in item_rows:
        module = item["module"]
        tasks_table, subtasks_table = TASK_MODULES[module]

        task_row = conn.execute(
            f"SELECT * FROM {tasks_table} WHERE id = ?",
            (item["task_id"],),
        ).fetchone()

        subtask_rows = conn.execute(
            f"SELECT * FROM {subtasks_table} WHERE task_id = ? ORDER BY id ASC",
            (item["task_id"],),
        ).fetchall()

        resolved.append({
            "item_id": item["id"],
            "module": module,
            "nature": MODULE_LABELS[module],
            "position": item["position"],
            "task": _serialize_task(task_row, subtask_rows),
        })

    return resolved


def normalize_positions(conn, line_id):
    """Renumera `line_items.position` a una secuencia contigua `0..n-1`.

    Reasigna la `position` de cada ítem de la línea `line_id` a su índice
    de base 0 según el orden actual, produciendo una secuencia total, sin
    huecos y sin duplicados (`0, 1, 2, ...`, FR-07/Req 1.7). Se invoca tras
    cada alta, baja o reordenamiento para que el orden quede siempre
    normalizado, independientemente de los valores de `position` previos
    (que pueden tener huecos o empates tras esas operaciones).

    El orden de referencia es `position ASC` con desempate estable por
    `id ASC`: si dos ítems comparten `position` (p. ej. justo después de un
    reordenamiento que los dejó transitoriamente iguales), el de menor `id`
    queda primero, de modo que el resultado es determinista.

    Esta función **no** confirma (`commit`) ni revierte (`rollback`): opera
    con la conexión que le pasa el llamador, que es quien controla la
    transacción. Los endpoints de mutación (añadir/eliminar/reordenar) la
    invocan dentro de una única transacción y hacen `rollback` ante cualquier
    excepción, siguiendo el patrón de rotación atómica de
    `auth.generate_api_token`, para que un fallo nunca deje las posiciones en
    un estado inconsistente (no contiguo). No crea ni modifica ninguna tarea.
    """
    rows = conn.execute(
        """SELECT id
           FROM line_items
           WHERE line_id = ?
           ORDER BY position ASC, id ASC""",
        (line_id,),
    ).fetchall()

    for index, row in enumerate(rows):
        conn.execute(
            "UPDATE line_items SET position = ? WHERE id = ?",
            (index, row["id"]),
        )


# ---------- API: lectura de la línea ----------

@line_bp.route("/api/line", methods=["GET"])
def get_line():
    """Devuelve la línea del usuario actual como un arreglo JSON ordenado.

    Resuelve la única línea del usuario de la sesión con `resolve_line`, que
    primero barre las referencias colgantes (FR-11/Req 1.11) y luego devuelve
    los ítems restantes ordenados por `position ASC`, cada uno con su tarea
    subyacente y la lista de subtareas siempre presente (FR-09/Req 1.9).

    El resultado es un arreglo JSON (posiblemente vacío) de ítems serializados
    con la forma del diseño. Sigue el patrón de apertura/cierre explícito de
    conexión de `calendar_module.py`: abre con `database.get_connection()`,
    resuelve, cierra la conexión y responde `200` con `jsonify`.

    El `user_id` se toma de `session["user_id"]`; la guardia `before_request`
    ya garantiza que exista una sesión activa para las rutas `/api/`.
    """
    conn = get_connection()
    result = resolve_line(conn, session["user_id"])
    conn.close()
    return jsonify(result)

@line_bp.route("/api/line/available", methods=["GET"])
def get_available_tasks():
    """Devuelve las tareas existentes del usuario agrupadas por naturaleza.

    Alimenta el selector (picker) de la página: para añadir puntos a la línea,
    el usuario elige entre las tareas que ya tiene en los tres módulos. La
    respuesta es un objeto JSON cuyas claves son los módulos y cuyos valores
    son listas de las tareas del usuario en ese módulo::

        {
          "academic": [ { ...tarea..., "subtasks": [...] }, ... ],
          "work":     [ ... ],
          "personal": [ ... ]
        }

    Cada tarea se serializa igual que en `resolve_line` (vía `_serialize_task`
    más la consulta de subtareas ordenadas por `id ASC`), de modo que el shape
    de la tarea en el selector coincide con el de la línea ya resuelta
    (FR-09/Req 1.9): la clave `subtasks` siempre está presente (lista vacía si
    la tarea no tiene subtareas).

    Parámetro de consulta opcional `?module`:

    - Ausente → se devuelven los tres grupos (`academic`, `work`, `personal`),
      cada uno con las tareas del usuario en ese módulo (Req 1.2, 1.5).
    - Una clave válida de `VALID_MODULES` → se devuelve un objeto con sólo ese
      grupo.
    - Cualquier otro valor → `400 {"error": ...}` con mensaje en español,
      consistente con el resto de módulos, sin tocar la base de datos.

    Todas las consultas filtran por `session["user_id"]`, de modo que nunca se
    exponen tareas de otro usuario (Req 1.2). Sigue el patrón de apertura/cierre
    explícito de conexión de `calendar_module.py`.
    """
    module = request.args.get("module")
    if module is not None and module not in VALID_MODULES:
        return jsonify({"error": f"Módulo no válido: {module}"}), 400

    if module is None:
        modules = list(TASK_MODULES.keys())
    else:
        modules = [module]

    user_id = session["user_id"]

    conn = get_connection()
    try:
        grouped = {}
        for module_key in modules:
            tasks_table, subtasks_table = TASK_MODULES[module_key]
            task_rows = conn.execute(
                f"SELECT * FROM {tasks_table} WHERE user_id = ?",
                (user_id,),
            ).fetchall()

            serialized = []
            for task_row in task_rows:
                subtask_rows = conn.execute(
                    f"SELECT * FROM {subtasks_table} WHERE task_id = ? ORDER BY id ASC",
                    (task_row["id"],),
                ).fetchall()
                serialized.append(_serialize_task(task_row, subtask_rows))

            grouped[module_key] = serialized
    finally:
        conn.close()

    return jsonify(grouped)

# ---------- API: mutación de la línea ----------

@line_bp.route("/api/line/items", methods=["POST"])
def add_line_item():
    """Añade al final de la línea una tarea existente del usuario.

    Lee el cuerpo JSON `{"module": "...", "task_id": N}` (igual que
    `calendar_module.create_event`, con `request.get_json(force=True)`) y
    valida en este orden, con mensajes en español consistentes con el resto de
    módulos:

    1. `module` ausente o no válido (fuera de `VALID_MODULES`), o `task_id`
       ausente o no entero → `400 {"error": ...}`.
    2. `(module, task_id)` no es una tarea existente del usuario de la sesión
       (comprobado con `task_exists`) → `404 {"error": ...}`. Así nunca se
       filtran tareas de otro usuario.
    3. `(module, task_id)` ya está presente en la línea del usuario →
       `409 {"error": ...}` (una tarea aparece a lo sumo una vez).

    Si pasa todas las validaciones, obtiene (o crea) la línea del usuario con
    `get_or_create_line`, inserta el nuevo `line_item` al final (posición
    `max(position) + 1`; el valor exacto no importa porque a continuación se
    normaliza) y renumera las posiciones con `normalize_positions`. La
    inserción y la normalización corren en una **única transacción** con
    `rollback` ante cualquier excepción, replicando el patrón de rotación
    atómica de `auth.generate_api_token`, de modo que un fallo nunca deja las
    posiciones en un estado inconsistente.

    Tras confirmar, re-resuelve la línea (`resolve_line`) y devuelve `201` con
    el ítem resuelto recién añadido (el que coincide con `(module, task_id)`),
    en la forma serializada del diseño (`{item_id, module, nature, position,
    task:{...subtasks...}}`).

    El `user_id` se toma de `session["user_id"]`; la guardia `before_request`
    ya garantiza que exista una sesión activa para las rutas `/api/`.
    """
    data = request.get_json(force=True)
    module = data.get("module")
    task_id = data.get("task_id")

    # 1. Validación de entrada (400): módulo válido y task_id entero.
    #    `bool` se excluye explícitamente porque es subclase de `int`.
    if module not in VALID_MODULES:
        return jsonify({"error": f"Módulo no válido: {module}"}), 400
    if not isinstance(task_id, int) or isinstance(task_id, bool):
        return jsonify({"error": "task_id debe ser un entero"}), 400

    user_id = session["user_id"]

    conn = get_connection()
    try:
        # 2. La tarea debe existir y pertenecer al usuario de la sesión (404).
        if not task_exists(conn, module, task_id, user_id):
            return jsonify({"error": "Tarea no encontrada"}), 404

        line_id = get_or_create_line(conn, user_id)

        # 3. La tarea no puede estar ya en la línea (409, unicidad).
        duplicate = conn.execute(
            "SELECT 1 FROM line_items WHERE line_id = ? AND module = ? AND task_id = ?",
            (line_id, module, task_id),
        ).fetchone()
        if duplicate is not None:
            return jsonify({"error": "La tarea ya está en la línea"}), 409

        # Alta al final + normalización en una única transacción.
        try:
            max_row = conn.execute(
                "SELECT MAX(position) AS max_pos FROM line_items WHERE line_id = ?",
                (line_id,),
            ).fetchone()
            next_position = 0 if max_row["max_pos"] is None else max_row["max_pos"] + 1

            conn.execute(
                "INSERT INTO line_items (line_id, module, task_id, position) VALUES (?, ?, ?, ?)",
                (line_id, module, task_id, next_position),
            )
            normalize_positions(conn, line_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Re-resuelve la línea y localiza el ítem recién añadido por su par
        # (module, task_id), devolviéndolo en la forma serializada del diseño.
        resolved = resolve_line(conn, user_id)
    finally:
        conn.close()

    new_item = next(
        item
        for item in resolved
        if item["module"] == module and item["task"]["id"] == task_id
    )
    return jsonify(new_item), 201


@line_bp.route("/api/line/items/<int:item_id>", methods=["DELETE"])
def delete_line_item(item_id):
    """Elimina un ítem de la línea del usuario y renumera las posiciones.

    Quita de la línea el `line_item` identificado por `item_id`, pero sólo si
    pertenece a la línea del usuario de la sesión. Esto evita operar sobre el
    ítem de otro usuario: se obtiene (o crea) la línea del usuario con
    `get_or_create_line` y se comprueba que exista una fila en `line_items`
    con `id == item_id` y `line_id` igual al de esa línea.

    - Si el ítem no existe o no pertenece a la línea del usuario →
      `404 {"error": ...}` con mensaje en español, consistente con el resto de
      módulos (nunca se filtra ni se altera el ítem de otro usuario).
    - En caso contrario: borra el ítem, renumera las posiciones con
      `normalize_positions` (para que queden contiguas `0..n-1` tras la baja,
      FR-07/Req 1.7) y confirma. El borrado y la normalización corren en una
      **única transacción** con `rollback` ante cualquier excepción, replicando
      el patrón de rotación atómica de `auth.generate_api_token`, de modo que
      un fallo nunca deja las posiciones en un estado inconsistente.

    Devuelve `200 {"ok": true}` tras confirmar. El `user_id` se toma de
    `session["user_id"]`; la guardia `before_request` ya garantiza que exista
    una sesión activa para las rutas `/api/`. Sigue el patrón de apertura/cierre
    explícito de conexión del resto del módulo.
    """
    user_id = session["user_id"]

    conn = get_connection()
    try:
        line_id = get_or_create_line(conn, user_id)

        # El ítem debe existir y pertenecer a la línea del usuario (404).
        owned = conn.execute(
            "SELECT 1 FROM line_items WHERE id = ? AND line_id = ?",
            (item_id, line_id),
        ).fetchone()
        if owned is None:
            return jsonify({"error": "Ítem no encontrado"}), 404

        # Baja + normalización en una única transacción.
        try:
            conn.execute("DELETE FROM line_items WHERE id = ?", (item_id,))
            normalize_positions(conn, line_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    return jsonify({"ok": True}), 200


@line_bp.route("/api/line/order", methods=["PUT"])
def reorder_line():
    """Define el orden completo de la línea del usuario y renumera posiciones.

    Lee el cuerpo JSON `{"item_ids": [id, id, ...]}` (igual que el resto de
    mutaciones del módulo, con `request.get_json(force=True)`) donde `item_ids`
    es la secuencia completa de los `line_items.id` del usuario en el nuevo
    orden deseado. Valida en este orden, con mensajes en español consistentes
    con el resto de módulos (y sin alterar la línea ante un error):

    1. `item_ids` debe ser una lista → en otro caso `400 {"error": ...}`.
    2. El conjunto enviado debe coincidir **exactamente** con los ids actuales
       de la línea del usuario: se rechaza (`400 {"error": ...}`) si falta algún
       id, si sobra o es ajeno (no pertenece a la línea del usuario) o si hay
       ids duplicados. Se comparan tanto la longitud (para detectar duplicados)
       como la igualdad de conjuntos (para detectar faltantes/ajenos).

    Si pasa las validaciones, asigna a cada ítem su nueva `position` según el
    índice en `item_ids` (`position = i`) y luego llama a `normalize_positions`
    para garantizar una secuencia contigua `0..n-1` sin huecos ni duplicados
    (FR-07/Req 1.7). Las actualizaciones de posición y la normalización corren
    en una **única transacción** con `rollback` ante cualquier excepción,
    replicando el patrón de rotación atómica de `auth.generate_api_token`, de
    modo que un fallo nunca deja las posiciones en un estado inconsistente.

    Tras confirmar, re-resuelve la línea (`resolve_line`) y devuelve `200` con
    la línea reordenada en la forma serializada del diseño. El `user_id` se toma
    de `session["user_id"]`; la guardia `before_request` ya garantiza que exista
    una sesión activa para las rutas `/api/`. Sigue el patrón de apertura/cierre
    explícito de conexión del resto del módulo.
    """
    data = request.get_json(force=True)
    item_ids = data.get("item_ids")

    # 1. `item_ids` debe ser una lista (400).
    if not isinstance(item_ids, list):
        return jsonify({"error": "item_ids debe ser una lista"}), 400

    user_id = session["user_id"]

    conn = get_connection()
    try:
        line_id = get_or_create_line(conn, user_id)

        # Ids actuales de la línea del usuario.
        current_rows = conn.execute(
            "SELECT id FROM line_items WHERE line_id = ?",
            (line_id,),
        ).fetchall()
        current_ids = {row["id"] for row in current_rows}

        # 2. El conjunto enviado debe coincidir exactamente con los ids
        #    actuales: se compara la longitud (detecta duplicados) y la
        #    igualdad de conjuntos (detecta faltantes/ajenos).
        if len(item_ids) != len(current_ids) or set(item_ids) != current_ids:
            return jsonify(
                {"error": "item_ids debe coincidir exactamente con los ítems de la línea"}
            ), 400

        # Aplica la permutación + normalización en una única transacción.
        try:
            for index, item_id in enumerate(item_ids):
                conn.execute(
                    "UPDATE line_items SET position = ? WHERE id = ? AND line_id = ?",
                    (index, item_id, line_id),
                )
            normalize_positions(conn, line_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        resolved = resolve_line(conn, user_id)
    finally:
        conn.close()

    return jsonify(resolved), 200
