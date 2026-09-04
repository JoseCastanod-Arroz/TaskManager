import sys
from datetime import date, datetime
from flask import Flask, jsonify, request, render_template
from database import get_connection, init_db
from calendar_module import calendar_bp, init_calendar_db

app = Flask(__name__)
app.register_blueprint(calendar_bp)

VALID_SORT = {"complexity", "due_date", "title", "created_at", "urgency"}

# Cuántos "días" vale cada punto de complejidad a la hora de calcular la
# urgencia. Con 15, una tarea de complejidad alta (3) sin fecha próxima
# pesa aproximadamente lo mismo que una tarea simple que vence en ~30 días
# más pronto.
COMPLEXITY_DAY_WEIGHT = 15

# Si una tarea no tiene fecha de entrega, se le asigna esta cantidad de
# "días restantes" para que quede muy abajo en la lista de urgencia
# (no compite con las que sí tienen fecha).
NO_DUE_DATE_DAYS = 9999


def _days_left(due_date):
    """Días que faltan para la fecha de entrega (negativo si ya venció)."""
    if not due_date:
        return NO_DUE_DATE_DAYS
    try:
        due = datetime.strptime(due_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return NO_DUE_DATE_DAYS
    return (due - date.today()).days


def _urgency_score(task):
    """Entre más alto, más urgente: pesa la complejidad y lo cerca que
    está la fecha de entrega (una tarea vencida es aún más urgente)."""
    days_left = _days_left(task.get("due_date"))
    return (task.get("complexity") or 0) * COMPLEXITY_DAY_WEIGHT - days_left


# ---------- Frontend ----------

@app.route("/")
def index():
    return render_template("index.html")


# ---------- Tareas ----------

@app.route("/api/tasks", methods=["GET"])
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
    query = "SELECT * FROM tasks"
    params = []
    if subject:
        query += " WHERE subject = ?"
        params.append(subject)

    if sort_by != "urgency":
        query += f" ORDER BY {sort_by} {order}"

    rows = conn.execute(query, params).fetchall()
    tasks = [dict(r) for r in rows]

    # cantidad de subtareas por tarea (para el listado, sin traer el detalle completo)
    for t in tasks:
        c = conn.execute(
            "SELECT COUNT(*) AS total, SUM(completed) AS done FROM subtasks WHERE task_id = ?",
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


@app.route("/api/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id):
    conn = get_connection()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        conn.close()
        return jsonify({"error": "Tarea no encontrada"}), 404

    subtasks = conn.execute(
        "SELECT * FROM subtasks WHERE task_id = ? ORDER BY created_at ASC", (task_id,)
    ).fetchall()
    conn.close()

    result = dict(task)
    result["subtasks"] = [dict(s) for s in subtasks]
    return jsonify(result)


@app.route("/api/tasks", methods=["POST"])
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
        "INSERT INTO tasks (title, description, due_date, complexity, subject) VALUES (?, ?, ?, ?, ?)",
        (title, description, due_date, complexity, subject),
    )
    conn.commit()
    new_id = cur.lastrowid
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return jsonify(dict(task)), 201


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    data = request.get_json(force=True)
    conn = get_connection()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Tarea no encontrada"}), 404

    title = data.get("title", existing["title"])
    description = data.get("description", existing["description"])
    due_date = data.get("due_date", existing["due_date"])
    complexity = data.get("complexity", existing["complexity"])
    subject = data.get("subject", existing["subject"])

    conn.execute(
        "UPDATE tasks SET title=?, description=?, due_date=?, complexity=?, subject=? WHERE id=?",
        (title, description, due_date, complexity, subject, task_id),
    )
    conn.commit()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return jsonify(dict(task))


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    conn = get_connection()
    existing = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Tarea no encontrada"}), 404
    conn.execute("DELETE FROM subtasks WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------- Subtareas ----------

@app.route("/api/tasks/<int:task_id>/subtasks", methods=["POST"])
def create_subtask(task_id):
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title es obligatorio"}), 400

    conn = get_connection()
    task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        conn.close()
        return jsonify({"error": "Tarea no encontrada"}), 404

    cur = conn.execute(
        "INSERT INTO subtasks (task_id, title, completed) VALUES (?, ?, 0)",
        (task_id, title),
    )
    conn.commit()
    new_id = cur.lastrowid
    subtask = conn.execute("SELECT * FROM subtasks WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return jsonify(dict(subtask)), 201


@app.route("/api/subtasks/<int:subtask_id>", methods=["PUT"])
def update_subtask(subtask_id):
    data = request.get_json(force=True)
    conn = get_connection()
    existing = conn.execute("SELECT * FROM subtasks WHERE id = ?", (subtask_id,)).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Subtarea no encontrada"}), 404

    title = data.get("title", existing["title"])
    completed = data.get("completed", existing["completed"])
    completed = 1 if completed else 0

    conn.execute(
        "UPDATE subtasks SET title=?, completed=? WHERE id=?",
        (title, completed, subtask_id),
    )
    conn.commit()
    subtask = conn.execute("SELECT * FROM subtasks WHERE id = ?", (subtask_id,)).fetchone()
    conn.close()
    return jsonify(dict(subtask))


@app.route("/api/subtasks/<int:subtask_id>", methods=["DELETE"])
def delete_subtask(subtask_id):
    conn = get_connection()
    existing = conn.execute("SELECT id FROM subtasks WHERE id = ?", (subtask_id,)).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Subtarea no encontrada"}), 404
    conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------- Utilidad ----------

@app.route("/api/subjects", methods=["GET"])
def list_subjects():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT subject FROM tasks ORDER BY subject ASC").fetchall()
    conn.close()
    return jsonify([r["subject"] for r in rows])


def ask_port():
    default_port = 5000
    try:
        raw = input(f"Puerto para ejecutar el servidor [{default_port}]: ").strip()
    except EOFError:
        raw = ""
    if not raw:
        return default_port
    try:
        return int(raw)
    except ValueError:
        print(f"Puerto inválido, usando {default_port} por defecto.")
        return default_port


if __name__ == "__main__":
    init_db()
    init_calendar_db()
    port = ask_port()
    print(f"Servidor disponible en http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
