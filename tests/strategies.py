"""Estrategias base de Hypothesis (feature: external-data-api).

Generadores reutilizables para las pruebas basadas en propiedades: usuarios,
tareas, subtareas y eventos. Están diseñados para ejercitar los casos que
importan a las propiedades de corrección del diseño:

- Tareas con campos opcionales (``description``, ``due_date``, ``subject``,
  ``complexity``) que a veces son ``None`` -> Property 8 (opcionales nulos).
- ``created_at``/``event_date`` con valores repetidos (empates) -> orden estable
  por ``id`` de las Properties 7, 12 y 13.
- Cantidad variable de subtareas por tarea (incluyendo 0) -> Property 9.
- Módulos elegidos entre ``academic``/``work``/``personal`` -> Properties 7 y 10.

Los generadores devuelven ``dict`` planos (datos puros). Las funciones ``insert_*``
son utilidades para materializar esos datos en una conexión SQLite ya
inicializada por las fixtures de ``conftest`` y devolver el ``id`` insertado.
"""

from __future__ import annotations

from hypothesis import strategies as st

# Claves de módulo de tareas -> (tabla_tareas, tabla_subtareas).
TASK_MODULES = {
    "academic": ("tasks", "subtasks"),
    "work": ("work_tasks", "work_subtasks"),
    "personal": ("personal_tasks", "personal_subtasks"),
}
MODULE_KEYS = sorted(TASK_MODULES.keys())

# Módulos válidos para eventos de calendario (según calendar_module).
EVENT_MODULES = ["academic", "work", "personal", "general"]


# ---------- Generadores de texto base ----------

def _text(min_size=1, max_size=40):
    """Texto imprimible sin caracteres de control ni espacios en los bordes."""
    return st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF, blacklist_categories=("Cs",)),
        min_size=min_size,
        max_size=max_size,
    ).map(lambda s: s.strip()).filter(lambda s: len(s) >= min_size)


# Nombres de usuario: no vacíos, sin espacios, únicos entre generaciones se
# garantiza en la utilidad de inserción (con sufijo) para evitar colisiones
# por la restricción UNIQUE de ``users.username``.
usernames = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
    min_size=3,
    max_size=20,
)


# ---------- Fechas y timestamps ----------

# Fechas ``YYYY-MM-DD`` en un rango acotado (años/meses limitados) para que
# aparezcan empates de mes y ejercitar el filtrado/orden por fecha.
dates = st.builds(
    lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    st.integers(min_value=2024, max_value=2026),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)

# Timestamps ``YYYY-MM-DD HH:MM:SS`` con un conjunto pequeño de valores para
# forzar empates de ``created_at`` (ejercita el desempate por ``id``).
created_ats = st.builds(
    lambda d, hh, mm: f"{d} {hh:02d}:{mm:02d}:00",
    st.sampled_from(["2024-01-01", "2024-06-15", "2025-03-10", "2026-02-20"]),
    st.integers(min_value=0, max_value=23),
    st.sampled_from([0, 30]),
)


# ---------- Generadores de entidades (dicts de datos) ----------

@st.composite
def tasks(draw, module=None):
    """Genera una tarea válida a nivel de esquema.

    Nota importante sobre nullabilidad (esquema real de ``tasks``/``work_tasks``/
    ``personal_tasks``):
    - ``description`` y ``due_date`` **sí** admiten ``NULL`` en la base -> se
      generan opcionalmente como ``None`` para ejercitar la Property 8.
    - ``subject`` (``NOT NULL``) y ``complexity`` (``NOT NULL DEFAULT 1``) **no**
      admiten ``NULL`` en almacenamiento, así que siempre llevan valor. La
      Property 8 cubre esos campos a nivel de serialización de la respuesta, no
      de almacenamiento.

    ``module`` fija el módulo; si es ``None`` se elige uno de los tres.
    """
    return {
        "title": draw(_text(min_size=1, max_size=60)),
        "description": draw(st.none() | _text(max_size=120)),
        "due_date": draw(st.none() | dates),
        "complexity": draw(st.integers(min_value=1, max_value=5)),
        "subject": draw(_text(min_size=1, max_size=30)),
        "created_at": draw(created_ats),
        "module": module if module is not None else draw(st.sampled_from(MODULE_KEYS)),
    }


@st.composite
def subtasks(draw, max_count=4):
    """Genera una lista de 0..``max_count`` subtareas (id/orden por inserción)."""
    n = draw(st.integers(min_value=0, max_value=max_count))
    return [
        {
            "title": draw(_text(min_size=1, max_size=40)),
            "completed": draw(st.booleans()),
        }
        for _ in range(n)
    ]


@st.composite
def events(draw, module=None):
    """Genera un evento de calendario con fechas que pueden repetir mes."""
    return {
        "title": draw(_text(min_size=1, max_size=60)),
        "description": draw(st.none() | _text(max_size=120)),
        "event_date": draw(dates),
        "module": module if module is not None else draw(st.sampled_from(EVENT_MODULES)),
        "created_at": draw(created_ats),
    }


# ---------- Utilidades de inserción en la base de pruebas ----------

_username_counter = {"n": 0}


def _unique_username(base: str) -> str:
    """Evita colisiones con la restricción UNIQUE de ``users.username``."""
    _username_counter["n"] += 1
    safe = (base or "user").strip() or "user"
    return f"{safe}_{_username_counter['n']}"


def insert_user(conn, username="user", password_hash="x") -> int:
    """Inserta un usuario y devuelve su ``id``. El nombre se hace único."""
    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (_unique_username(username), password_hash),
    )
    conn.commit()
    return cur.lastrowid


def insert_task(conn, user_id: int, task: dict) -> int:
    """Inserta una tarea (dict de ``tasks(...)``) para ``user_id``.

    Devuelve el ``id`` de la tarea insertada. Respeta el ``module`` del dict.
    """
    tasks_table, _ = TASK_MODULES[task["module"]]
    cur = conn.execute(
        f"INSERT INTO {tasks_table} "
        "(title, description, due_date, complexity, subject, created_at, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            task["title"],
            task["description"],
            task["due_date"],
            task["complexity"],
            task["subject"],
            task["created_at"],
            user_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_subtasks(conn, module: str, task_id: int, subtask_list: list) -> list:
    """Inserta subtareas para una tarea y devuelve la lista de ``id`` creados."""
    _, subtasks_table = TASK_MODULES[module]
    ids = []
    for sub in subtask_list:
        cur = conn.execute(
            f"INSERT INTO {subtasks_table} (task_id, title, completed) VALUES (?, ?, ?)",
            (task_id, sub["title"], 1 if sub["completed"] else 0),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def insert_event(conn, user_id: int, event: dict) -> int:
    """Inserta un evento (dict de ``events(...)``) para ``user_id``."""
    cur = conn.execute(
        "INSERT INTO events (title, description, event_date, module, created_at, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            event["title"],
            event["description"],
            event["event_date"],
            event["module"],
            event["created_at"],
            user_id,
        ),
    )
    conn.commit()
    return cur.lastrowid
