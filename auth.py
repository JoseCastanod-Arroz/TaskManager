"""
Módulo de autenticación
========================
Provee inicio de sesión basado en sesiones de Flask. Guarda los usuarios
en la tabla `users` de la misma base de datos SQLite, con la contraseña
cifrada (hash) usando Werkzeug. Expone:

- init_auth_db():        crea la tabla de usuarios (y un admin inicial).
- auth_bp:               blueprint con /login, /logout, /register, /change-password.
- login_required(fn):    decorador para proteger rutas de páginas.
- api_login_required(fn):decorador para proteger endpoints JSON (401).
- current_user():        devuelve el usuario en sesión o None.
"""

import os
from functools import wraps

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
    jsonify,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_connection

auth_bp = Blueprint("auth", __name__)


def init_auth_db():
    """Crea la tabla de usuarios y un usuario inicial si no existe ninguno.

    El usuario/clave iniciales se pueden fijar con las variables de entorno
    ADMIN_USER y ADMIN_PASSWORD. Por defecto: admin / admin123.
    """
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if count == 0:
        admin_user = os.environ.get("ADMIN_USER", "admin")
        admin_pass = os.environ.get("ADMIN_PASSWORD", "admin123")
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (admin_user, generate_password_hash(admin_pass)),
        )
        conn.commit()
        print(f"[auth] Usuario inicial creado: {admin_user} (cámbialo cuanto antes)")

    conn.close()


def current_user():
    """Devuelve el dict del usuario en sesión, o None si no hay sesión."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    conn = get_connection()
    row = conn.execute(
        "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def login_required(fn):
    """Protege una página: si no hay sesión, redirige al login."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("auth.login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def api_login_required(fn):
    """Protege un endpoint JSON: si no hay sesión, responde 401."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("user_id") is None:
            return jsonify({"error": "No autorizado"}), 401
        return fn(*args, **kwargs)

    return wrapper


# ---------- Rutas ----------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Si ya hay sesión activa, ir directo a la app.
    if session.get("user_id") is not None:
        return redirect(url_for("academic.page"))

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            # Evitar redirecciones abiertas: solo rutas internas.
            next_url = request.args.get("next") or request.form.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("academic.page"))

        error = "Usuario o contraseña incorrectos."

    return render_template("login.html", error=error, next=request.args.get("next", ""))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    error = None
    success = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if not username or not password:
            error = "Usuario y contraseña son obligatorios."
        elif len(password) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        elif password != confirm:
            error = "Las contraseñas no coinciden."
        else:
            conn = get_connection()
            exists = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if exists:
                error = "Ese usuario ya existe."
                conn.close()
            else:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                conn.commit()
                conn.close()
                success = "Cuenta creada. Ya puedes iniciar sesión."

    return render_template("register.html", error=error, success=success)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    error = None
    success = None
    if request.method == "POST":
        current = request.form.get("current") or ""
        new = request.form.get("new") or ""
        confirm = request.form.get("confirm") or ""

        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()

        if row is None or not check_password_hash(row["password_hash"], current):
            error = "La contraseña actual no es correcta."
            conn.close()
        elif len(new) < 6:
            error = "La nueva contraseña debe tener al menos 6 caracteres."
            conn.close()
        elif new != confirm:
            error = "Las contraseñas nuevas no coinciden."
            conn.close()
        elif new == current:
            error = "La nueva contraseña debe ser distinta a la actual."
            conn.close()
        else:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), session["user_id"]),
            )
            conn.commit()
            conn.close()
            success = "Contraseña actualizada correctamente."

    return render_template("change_password.html", error=error, success=success)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
