from flask import Flask
from calendar_module import calendar_bp, init_calendar_db
from tasks_module import create_tasks_module
from nav import NAV_LINKS

app = Flask(__name__)

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
    port = ask_port()
    print(f"Servidor disponible en http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
