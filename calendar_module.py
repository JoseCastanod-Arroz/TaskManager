"""
Módulo de Calendario
=====================
Módulo independiente del gestor de tareas: permite registrar eventos
importantes sobre una fecha. Tiene su propia tabla en la base de datos
y sus propias rutas (página + API). Se conecta a la app principal con
una sola línea (app.register_blueprint) y no depende de la lógica de
tareas/subtareas.
"""

from datetime import date
from flask import Blueprint, jsonify, request, render_template
from database import get_connection

calendar_bp = Blueprint("calendar", __name__)


def init_calendar_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            event_date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


# ---------- Frontend ----------

@calendar_bp.route("/calendar")
def calendar_page():
    return render_template("calendar.html")


# ---------- API: eventos ----------

@calendar_bp.route("/api/events", methods=["GET"])
def list_events():
    """Lista eventos. Filtros opcionales: ?month=YYYY-MM o ?date=YYYY-MM-DD"""
    month = request.args.get("month")
    event_date = request.args.get("date")

    conn = get_connection()
    query = "SELECT * FROM events"
    params = []
    if event_date:
        query += " WHERE event_date = ?"
        params.append(event_date)
    elif month:
        query += " WHERE event_date LIKE ?"
        params.append(f"{month}-%")
    query += " ORDER BY event_date ASC, created_at ASC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@calendar_bp.route("/api/events/<int:event_id>", methods=["GET"])
def get_event(event_id):
    conn = get_connection()
    event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    if event is None:
        return jsonify({"error": "Evento no encontrado"}), 404
    return jsonify(dict(event))


@calendar_bp.route("/api/events", methods=["POST"])
def create_event():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    event_date = (data.get("event_date") or "").strip()
    description = data.get("description")

    if not title or not event_date:
        return jsonify({"error": "title y event_date son obligatorios"}), 400

    try:
        date.fromisoformat(event_date)
    except ValueError:
        return jsonify({"error": "event_date debe tener formato YYYY-MM-DD"}), 400

    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO events (title, description, event_date) VALUES (?, ?, ?)",
        (title, description, event_date),
    )
    conn.commit()
    new_id = cur.lastrowid
    event = conn.execute("SELECT * FROM events WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return jsonify(dict(event)), 201


@calendar_bp.route("/api/events/<int:event_id>", methods=["PUT"])
def update_event(event_id):
    data = request.get_json(force=True)
    conn = get_connection()
    existing = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Evento no encontrado"}), 404

    title = (data.get("title", existing["title"]) or "").strip() or existing["title"]
    description = data.get("description", existing["description"])
    event_date = data.get("event_date", existing["event_date"])

    try:
        date.fromisoformat(event_date)
    except ValueError:
        conn.close()
        return jsonify({"error": "event_date debe tener formato YYYY-MM-DD"}), 400

    conn.execute(
        "UPDATE events SET title=?, description=?, event_date=? WHERE id=?",
        (title, description, event_date, event_id),
    )
    conn.commit()
    event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return jsonify(dict(event))


@calendar_bp.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    conn = get_connection()
    existing = conn.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    if existing is None:
        conn.close()
        return jsonify({"error": "Evento no encontrado"}), 404
    conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
