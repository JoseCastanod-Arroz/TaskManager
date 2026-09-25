"""
Módulo de autenticación
========================
Provee inicio de sesión basado en sesiones de Flask. Guarda los usuarios
en la tabla `users` de la misma base de datos SQLite, con la contraseña
cifrada (hash) usando Werkzeug. Expone:

- init_auth_db():        crea la tabla de usuarios (y un admin inicial).
- init_api_tokens_db():  crea la tabla `api_tokens` para la API externa.
- auth_bp:               blueprint con /login, /logout, /register, /change-password.
- login_required(fn):    decorador para proteger rutas de páginas.
- api_login_required(fn):decorador para proteger endpoints JSON (401).
- current_user():        devuelve el usuario en sesión o None.
"""

import hashlib
import os
import secrets
from functools import wraps

from flask import (
    Blueprint,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
    jsonify,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_connection
from nav import NAV_LINKS

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


def init_api_tokens_db():
    """Crea la tabla `api_tokens` si no existe.

    Almacena un único token de API activo por usuario (columna `user_id`
    UNIQUE) guardando sólo el hash SHA-256 del valor en claro (`token_hash`),
    de modo que el token en claro no sea recuperable del registro.

    Debe invocarse después de `init_auth_db()` porque depende de la tabla
    `users` para la clave foránea.
    """
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_tokens (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL UNIQUE,
            token_hash  TEXT    NOT NULL UNIQUE,
            created_at  TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()


def _hash_token(raw_token: str) -> str:
    """Devuelve el SHA-256 hex (determinista) del token en claro.

    Un `Token_API` generado con `secrets.token_urlsafe(32)` tiene entropía
    suficiente para no necesitar salt, por lo que un hash determinista permite
    guardar sólo el hash e indexarlo para una búsqueda por igualdad O(1).
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_api_token(user_id: int) -> str:
    """Genera (o rota) el `Token_API` de un usuario y devuelve el valor en claro.

    Genera un token aleatorio con `secrets.token_urlsafe(32)` (~43 caracteres
    URL-safe, dentro del rango 32–128), calcula su hash SHA-256 y, en una
    **única transacción**, borra cualquier token previo del usuario e inserta
    el nuevo `(user_id, token_hash, created_at)`. Así se garantiza que exista
    un solo token activo por usuario (rotación, Req 2.3, 2.8).

    Ante cualquier excepción hace `rollback` y propaga el error sin dejar
    estado a medias: el token previo, si existía, queda intacto (Req 2.7).

    Devuelve el valor en claro `raw`; el llamador lo muestra una única vez, ya
    que en la base sólo se almacena el hash (Req 2.1).
    """
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)

    conn = get_connection()
    try:
        conn.execute("DELETE FROM api_tokens WHERE user_id = ?", (user_id,))
        conn.execute(
            "INSERT INTO api_tokens (user_id, token_hash) VALUES (?, ?)",
            (user_id, token_hash),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return raw


def revoke_api_token(user_id: int) -> bool:
    """Revoca (borra) el `Token_API` activo de un usuario.

    Borra la fila de `api_tokens` correspondiente al `user_id`. Devuelve
    `True` si existía un token y se eliminó, o `False` si el usuario no tenía
    ningún token activo que revocar (Req 2.4, 2.6).
    """
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM api_tokens WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def resolve_token_user(auth_header):
    """Resuelve el `Usuario_Propietario` a partir del `Authorization` header.

    Función pura de resolución usada por el decorador `token_required`.
    Devuelve un dict `{"id", "username"}` del usuario dueño del token, o
    `None` si la credencial es inválida o ausente:

    1. Si `auth_header` es `None` o no empieza por `Bearer ` → `None`
       (formato inválido / ausente, Req 1.2, 1.6).
    2. Se extrae el token tras `Bearer `; si está vacío o sólo contiene
       espacios → `None` (Req 1.5, 1.6).
    3. Se calcula su hash SHA-256 y se busca en `api_tokens`. Si no hay
       coincidencia → `None` (Req 1.3).
    4. Si hay coincidencia, hace `JOIN` con `users` y retorna `{id, username}`
       del Usuario_Propietario (Req 1.1).
    """
    prefix = "Bearer "
    if auth_header is None or not auth_header.startswith(prefix):
        return None

    raw = auth_header[len(prefix):]
    if not raw.strip():
        return None

    token_hash = _hash_token(raw)

    conn = get_connection()
    row = conn.execute(
        """
        SELECT users.id AS id, users.username AS username
        FROM api_tokens
        JOIN users ON users.id = api_tokens.user_id
        WHERE api_tokens.token_hash = ?
        """,
        (token_hash,),
    ).fetchone()
    conn.close()

    return dict(row) if row else None


def user_has_api_token(user_id: int) -> bool:
    """Indica si el usuario tiene un `Token_API` activo (sin exponer el valor)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM api_tokens WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


def token_required(fn):
    """Protege un endpoint de la API externa mediante `Token_API` (Bearer).

    Resuelve el usuario con `resolve_token_user` a partir del encabezado
    `Authorization`. Si la credencial es inválida o ausente, responde 401
    con un cuerpo JSON `{"error": ...}` (Req 1.2, 1.3, 1.6). En éxito guarda
    el usuario resuelto en `flask.g.api_user` (para que la vista filtre por
    `g.api_user["id"]`) y ejecuta la vista (Req 1.1).
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = resolve_token_user(request.headers.get("Authorization"))
        if user is None:
            return jsonify({"error": "Token de API inválido o ausente"}), 401
        g.api_user = user
        return fn(*args, **kwargs)

    return wrapper


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


# ---------- Emisión / revocación del Token_API (protegido por sesión) ----------

@auth_bp.route("/api/token", methods=["POST"])
@api_login_required
def issue_api_token():
    """Genera (o rota) el `Token_API` del usuario en sesión.

    Llama a `generate_api_token(session_user_id)` y devuelve el valor en claro
    exactamente una vez en `{"token": "<claro>"}` (Req 2.1, 2.3). El claro no se
    guarda en la base (sólo el hash), por lo que no existe forma de recuperarlo
    después (Req 2.2).

    Si falla la generación o el almacenamiento del token, responde 500 con
    `{"error": ...}` sin modificar el token previo del usuario: la operación es
    atómica y hace `rollback` ante cualquier excepción (Req 2.7).
    """
    user_id = session["user_id"]
    try:
        raw = generate_api_token(user_id)
    except Exception:
        return jsonify({"error": "No se pudo emitir el token"}), 500
    return jsonify({"token": raw}), 201


@auth_bp.route("/api/token", methods=["DELETE"])
@api_login_required
def delete_api_token():
    """Revoca el `Token_API` activo del usuario en sesión.

    Llama a `revoke_api_token(session_user_id)`. Si el usuario tenía un token
    activo lo invalida y responde 200 con un mensaje de éxito (Req 2.4). Si no
    tenía ningún token activo, responde 404 con `{"error": ...}` indicando que
    no hay token que revocar, sin modificar el estado de ningún token (Req 2.6).
    """
    user_id = session["user_id"]
    if revoke_api_token(user_id):
        return jsonify({"message": "Token revocado"}), 200
    return jsonify({"error": "No hay un token activo para revocar"}), 404


@auth_bp.route("/api/token/manage", methods=["GET"])
@login_required
def manage_api_token():
    """Página web para emitir/revocar el `Token_API` desde la interfaz.

    Protegida por sesión: si no hay sesión, `login_required` redirige al login.
    No muestra ningún token en claro (sólo se puede ver al emitirlo vía JS);
    únicamente informa si ya existe uno activo.
    """
    has_token = user_has_api_token(session["user_id"])
    return render_template(
        "api_token.html",
        has_token=has_token,
        nav_links=NAV_LINKS,
    )
