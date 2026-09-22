import os
from flask import Flask
from calendar_module import calendar_bp, init_calendar_db
from tasks_module import create_tasks_module
from auth import auth_bp, init_auth_db
from nav import NAV_LINKS

app = Flask(__name__)

# Clave para firmar las cookies de sesión. En producción, fíjala con la
# variable de entorno SECRET_KEY. Si no está definida, se genera una
# aleatoria por arranque (las sesiones no sobreviven a un reinicio).
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)

# Endurecer las cookies de sesión. El TLS lo termina el túnel, así que la
# app sirve por HTTP plano. La cookie Secure queda desactivada por defecto;
# si algún día sirves directamente por HTTPS, ponla en True con
# SESSION_COOKIE_SECURE=1 en el entorno.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
)

# ---------- Módulo académico (el original: pensum, materias) ----------
academic_bp = create_tasks_module(
    name="academic",
    tasks_table="tasks",
    subtasks_table="subtasks",
    tasks_prefix="/api/tasks",
    subtasks_prefix="/api/subtasks",
    page_route="/",
    template_name="tasks.html",
    page_title="Académico",
    subject_label="Materia",
    nav_links=NAV_LINKS,
)

# ---------- Módulo laboral / externo (trabajo, cursos, IEEE, talleres) ----------
work_bp = create_tasks_module(
    name="work",
    tasks_table="work_tasks",
    subtasks_table="work_subtasks",
    tasks_prefix="/api/work-tasks",
    subtasks_prefix="/api/work-subtasks",
    page_route="/trabajo",
    template_name="tasks.html",
    page_title="Trabajo",
    subject_label="Categoría",
    nav_links=NAV_LINKS,
)

# ---------- Módulo personal (amigos, casa, vida personal) ----------
personal_bp = create_tasks_module(
    name="personal",
    tasks_table="personal_tasks",
    subtasks_table="personal_subtasks",
    tasks_prefix="/api/personal-tasks",
    subtasks_prefix="/api/personal-subtasks",
    page_route="/personal",
    template_name="tasks.html",
    page_title="Personal",
    subject_label="Categoría",
    nav_links=NAV_LINKS,
)

app.register_blueprint(auth_bp)
app.register_blueprint(academic_bp)
app.register_blueprint(work_bp)
app.register_blueprint(personal_bp)
app.register_blueprint(calendar_bp)


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
    academic_bp.init_db()
    work_bp.init_db()
    personal_bp.init_db()
    init_calendar_db()
    init_auth_db()
    port = ask_port()
    print(f"Servidor disponible en http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
