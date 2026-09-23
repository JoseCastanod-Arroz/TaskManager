"""
Fábrica de módulos de tareas
=============================
Genera un Blueprint de Flask con la MISMA lógica que el gestor de tareas
original (CRUD de tareas + subtareas, orden por urgencia, agrupar por
"materia"/categoría), pero apuntando a sus propias tablas en la base de
datos. Esto permite tener varios módulos independientes (académico,
laboral, personal) sin duplicar código, cada uno con su propia página y
su propia API, todos compartiendo el módulo de calendario.
"""

from datetime import date, datetime
from flask import Blueprint, jsonify, request, render_template, redirect, url_for, session
from database import get_connection

VALID_SORT = {"complexity", "due_date", "title", "created_at", "urgency"}

# Cuántos "días" vale cada punto de complejidad a la hora de calcular la
# urgencia (igual que en el módulo original).
COMPLEXITY_DAY_WEIGHT = 15
NO_DUE_DATE_DAYS = 9999


def _days_left(due_date):
    if not due_date:
        return NO_DUE_DATE_DAYS
    try:
        due = datetime.strptime(due_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return NO_DUE_DATE_DAYS
    return (due - date.today()).days


def _urgency_score(task):
    days_left = _days_left(task.get("due_date"))
    return (task.get("complexity") or 0) * COMPLEXITY_DAY_WEIGHT - days_left


def create_tasks_module(
    *,
    name,
    tasks_table,
    subtasks_table,
    tasks_prefix,
    subtasks_prefix,
    page_route,
    template_name,
    page_title,
    subject_label,
    nav_links,
):
    """
    name: nombre único del blueprint (ej. "work")
    tasks_table / subtasks_table: nombres de las tablas propias del módulo
    tasks_prefix: prefijo de la API de tareas (ej. "/api/work-tasks")
    subtasks_prefix: prefijo de la API de subtareas (ej. "/api/work-subtasks")
    page_route: ruta de la página (ej. "/trabajo")
    subject_label: etiqueta a mostrar en vez de "Materia" (ej. "Categoría")
    nav_links: lista de dicts {href, label} para la barra de navegación
    """
    bp = Blueprint(name, __name__)

    # ---------- Autenticación ----------
    # Todas las rutas del módulo requieren sesión. Las páginas redirigen al
    # login; los endpoints de la API responden 401 en JSON.
    @bp.before_request
    def require_login():
        if session.get("user_id") is not None:
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "No autorizado"}), 401
        return redirect(url_for("auth.login", next=request.path))

    def init_db():
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {tasks_table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                due_date TEXT,
                complexity INTEGER NOT NULL DEFAULT 1,
                subject TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {subtasks_table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (task_id) REFERENCES {tasks_table} (id) ON DELETE CASCADE
            )
        """)

        # Migración multiusuario: agrega la columna user_id a la tabla de
        # tareas si no existe, y asigna los registros ya creados al primer
        # usuario (admin). Las subtareas heredan el dueño de su tarea padre,
        # por lo que no necesitan columna propia.
        cols = [row["name"] for row in cur.execute(f"PRAGMA table_info({tasks_table})")]
        if "user_id" not in cols:
            cur.execute(f"ALTER TABLE {tasks_table} ADD COLUMN user_id INTEGER")
            owner = cur.execute("SELECT MIN(id) AS id FROM users").fetchone()["id"]
            if owner is not None:
                cur.execute(
                    f"UPDATE {tasks_table} SET user_id = ? WHERE user_id IS NULL",
                    (owner,),
                )

        conn.commit()
        conn.close()

    # ---------- Frontend ----------

    @bp.route(page_route)
    def page():
        return render_template(
            template_name,
            page_title=page_title,
            subject_label=subject_label,
            api_base=tasks_prefix,
            subtasks_base=subtasks_prefix,
            nav_links=nav_links,
            module_key=name,
        )

    # ---------- Tareas ----------

    @bp.route(tasks_prefix, methods=["GET"])
    def list_tasks():
        sort_by = request.args.get("sort_by", "created_at")
        order = request.args.get("order", "asc").lower()
        subject = request.args.get("subject")
        group_by_subject = request.args.get("group_by") == "subject"

        if sort_by not in VALID_SORT:
            sort_by = "created_at"
        if order not in ("asc", "desc"):
            order = "asc"

        conn = get_connection()
        query = f"SELECT * FROM {tasks_table} WHERE user_id = ?"
        params = [session["user_id"]]
        if subject:
            query += " AND subject = ?"
            params.append(subject)

        if sort_by != "urgency":
            query += f" ORDER BY {sort_by} {order}"

        rows = conn.execute(query, params).fetchall()
        tasks = [dict(r) for r in rows]

        for t in tasks:
            c = conn.execute(
                f"SELECT COUNT(*) AS total, SUM(completed) AS done FROM {subtasks_table} WHERE task_id = ?",
                (t["id"],),
            ).fetchone()
            t["subtasks_total"] = c["total"] or 0
            t["subtasks_done"] = c["done"] or 0

        conn.close()

        if sort_by == "urgency":
            for t in tasks:
                t["urgency_score"] = _urgency_score(t)
            tasks.sort(key=lambda t: t["urgency_score"], reverse=(order == "desc"))

        if group_by_subject:
            grouped = {}
            for t in tasks:
                grouped.setdefault(t["subject"], []).append(t)
            return jsonify(grouped)

        return jsonify(tasks)

    @bp.route(f"{tasks_prefix}/<int:task_id>", methods=["GET"])
    def get_task(task_id):
        conn = get_connection()
        task = conn.execute(
            f"SELECT * FROM {tasks_table} WHERE id = ? AND user_id = ?",
            (task_id, session["user_id"]),
        ).fetchone()
        if task is None:
            conn.close()
            return jsonify({"error": "Tarea no encontrada"}), 404

        subtasks = conn.execute(
            f"SELECT * FROM {subtasks_table} WHERE task_id = ? ORDER BY created_at ASC", (task_id,)
        ).fetchall()
        conn.close()

        result = dict(task)
        result["subtasks"] = [dict(s) for s in subtasks]
        return jsonify(result)

    @bp.route(tasks_prefix, methods=["POST"])
    def create_task():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        subject = (data.get("subject") or "").strip()
        if not title or not subject:
            return jsonify({"error": "title y subject son obligatorios"}), 400

        complexity = int(data.get("complexity", 1))
        due_date = data.get("due_date")
        description = data.get("description")

        conn = get_connection()
        cur = conn.execute(
            f"INSERT INTO {tasks_table} (title, description, due_date, complexity, subject, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (title, description, due_date, complexity, subject, session["user_id"]),
        )
        conn.commit()
        new_id = cur.lastrowid
        task = conn.execute(f"SELECT * FROM {tasks_table} WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return jsonify(dict(task)), 201

    @bp.route(f"{tasks_prefix}/<int:task_id>", methods=["PUT"])
    def update_task(task_id):
        data = request.get_json(force=True)
        conn = get_connection()
        existing = conn.execute(
            f"SELECT * FROM {tasks_table} WHERE id = ? AND user_id = ?",
            (task_id, session["user_id"]),
        ).fetchone()
        if existing is None:
            conn.close()
            return jsonify({"error": "Tarea no encontrada"}), 404

        title = data.get("title", existing["title"])
        description = data.get("description", existing["description"])
        due_date = data.get("due_date", existing["due_date"])
        complexity = data.get("complexity", existing["complexity"])
        subject = data.get("subject", existing["subject"])

        conn.execute(
            f"UPDATE {tasks_table} SET title=?, description=?, due_date=?, complexity=?, subject=? WHERE id=?",
            (title, description, due_date, complexity, subject, task_id),
        )
        conn.commit()
        task = conn.execute(f"SELECT * FROM {tasks_table} WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return jsonify(dict(task))

    @bp.route(f"{tasks_prefix}/<int:task_id>", methods=["DELETE"])
    def delete_task(task_id):
        conn = get_connection()
        existing = conn.execute(
            f"SELECT id FROM {tasks_table} WHERE id = ? AND user_id = ?",
            (task_id, session["user_id"]),
        ).fetchone()
        if existing is None:
            conn.close()
            return jsonify({"error": "Tarea no encontrada"}), 404
        conn.execute(f"DELETE FROM {subtasks_table} WHERE task_id = ?", (task_id,))
        conn.execute(f"DELETE FROM {tasks_table} WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    # ---------- Subtareas ----------

    @bp.route(f"{tasks_prefix}/<int:task_id>/subtasks", methods=["POST"])
    def create_subtask(task_id):
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title es obligatorio"}), 400

        conn = get_connection()
        task = conn.execute(
            f"SELECT id FROM {tasks_table} WHERE id = ? AND user_id = ?",
            (task_id, session["user_id"]),
        ).fetchone()
        if task is None:
            conn.close()
            return jsonify({"error": "Tarea no encontrada"}), 404

        cur = conn.execute(
            f"INSERT INTO {subtasks_table} (task_id, title, completed) VALUES (?, ?, 0)",
            (task_id, title),
        )
        conn.commit()
        new_id = cur.lastrowid
        subtask = conn.execute(f"SELECT * FROM {subtasks_table} WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return jsonify(dict(subtask)), 201

    @bp.route(f"{subtasks_prefix}/<int:subtask_id>", methods=["PUT"])
    def update_subtask(subtask_id):
        data = request.get_json(force=True)
        conn = get_connection()
        existing = conn.execute(
            f"""SELECT s.* FROM {subtasks_table} s
                JOIN {tasks_table} t ON t.id = s.task_id
                WHERE s.id = ? AND t.user_id = ?""",
            (subtask_id, session["user_id"]),
        ).fetchone()
        if existing is None:
            conn.close()
            return jsonify({"error": "Subtarea no encontrada"}), 404

        title = data.get("title", existing["title"])
        completed = data.get("completed", existing["completed"])
        completed = 1 if completed else 0

        conn.execute(
            f"UPDATE {subtasks_table} SET title=?, completed=? WHERE id=?",
            (title, completed, subtask_id),
        )
        conn.commit()
        subtask = conn.execute(f"SELECT * FROM {subtasks_table} WHERE id = ?", (subtask_id,)).fetchone()
        conn.close()
        return jsonify(dict(subtask))

    @bp.route(f"{subtasks_prefix}/<int:subtask_id>", methods=["DELETE"])
    def delete_subtask(subtask_id):
        conn = get_connection()
        existing = conn.execute(
            f"""SELECT s.id FROM {subtasks_table} s
                JOIN {tasks_table} t ON t.id = s.task_id
                WHERE s.id = ? AND t.user_id = ?""",
            (subtask_id, session["user_id"]),
        ).fetchone()
        if existing is None:
            conn.close()
            return jsonify({"error": "Subtarea no encontrada"}), 404
        conn.execute(f"DELETE FROM {subtasks_table} WHERE id = ?", (subtask_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    # ---------- Utilidad ----------

    @bp.route(f"{tasks_prefix}/subjects", methods=["GET"])
    def list_subjects():
        conn = get_connection()
        rows = conn.execute(
            f"SELECT DISTINCT subject FROM {tasks_table} WHERE user_id = ? ORDER BY subject ASC",
            (session["user_id"],),
        ).fetchall()
        conn.close()
        return jsonify([r["subject"] for r in rows])

    bp.init_db = init_db
    return bp
