"""Property 8: Serialización completa de la tarea con opcionales nulos.

# Feature: external-data-api, Property 8: Serialización completa de la tarea con opcionales nulos

Valida que, para toda tarea devuelta por ``GET /api/v1/tasks``, el objeto JSON
contiene siempre exactamente el conjunto fijo de claves ``id``, ``title``,
``description``, ``due_date``, ``complexity``, ``subject``, ``created_at``,
``module`` y ``subtasks``; y que cualquier campo opcional sin valor almacenado
(en el esquema real: ``description`` y ``due_date`` admiten ``NULL``) aparece en
la respuesta como JSON ``null`` manteniendo la clave presente.

**Validates: Requirements 3.2, 3.3**

Notas de diseño
---------------
- El endpoint ``api_v1_bp`` aún no está registrado en la app real (tarea 8.1),
  así que la prueba monta un ``Flask`` mínimo, registra ``api_v1_bp`` y lo enlaza
  a la base temporal ya inicializada por la fixture ``temp_db``.
- La autenticación se hace emitiendo un token real con
  ``auth.generate_api_token(user_id)`` y presentándolo como cabecera Bearer.
- Los generadores de ``tests.strategies.tasks`` emiten ``None`` para
  ``description``/``due_date``, ejercitando así el caso de opcionales nulos.
"""

from __future__ import annotations

from flask import Flask
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api_module import api_v1_bp
from auth import generate_api_token
from database import get_connection
from tests.strategies import insert_user, insert_task, tasks


# Conjunto fijo de claves que toda tarea serializada debe exponer (Req 3.2).
_EXPECTED_TASK_KEYS = {
    "id",
    "title",
    "description",
    "due_date",
    "complexity",
    "subject",
    "created_at",
    "module",
    "subtasks",
}

# Campos opcionales que, en el esquema real, admiten ``NULL`` en almacenamiento
# y por tanto deben aparecer como JSON ``null`` cuando no tienen valor (Req 3.3).
_NULLABLE_FIELDS = ("description", "due_date")


def _build_test_app() -> Flask:
    """Crea una app Flask mínima con ``api_v1_bp`` registrado.

    La app queda enlazada a la base temporal porque ``get_connection`` lee
    ``database.DB_PATH`` (ya redirigido por la fixture ``temp_db``) en cada
    llamada.
    """
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    flask_app.register_blueprint(api_v1_bp)
    return flask_app


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(task_list=st.lists(tasks(), min_size=1, max_size=6))
def test_task_serialization_includes_fixed_keys_and_null_optionals(temp_db, task_list):
    """Toda tarea devuelta tiene el conjunto fijo de claves y nulos preservados."""
    conn = get_connection()
    user_id = insert_user(conn, "prop8")
    for task in task_list:
        insert_task(conn, user_id, task)
    conn.close()

    raw_token = generate_api_token(user_id)

    app = _build_test_app()
    client = app.test_client()
    resp = client.get(
        "/api/v1/tasks",
        headers={"Authorization": f"Bearer {raw_token}"},
    )

    assert resp.status_code == 200
    assert resp.is_json
    body = resp.get_json()
    assert isinstance(body, list)
    # Se insertó al menos una tarea; deben devolverse todas.
    assert len(body) == len(task_list)

    for serialized in body:
        # (Req 3.2) El conjunto de claves es exactamente el fijo: ni falta ni
        # sobra ninguna.
        assert set(serialized.keys()) == _EXPECTED_TASK_KEYS

    # (Req 3.3) Para cada campo opcional que se almacenó como None, la respuesta
    # debe traer la clave presente con valor null. Se casan por título para no
    # depender de un orden concreto (puede haber empates de created_at).
    by_title: dict[str, list[dict]] = {}
    for serialized in body:
        by_title.setdefault(serialized["title"], []).append(serialized)

    for task in task_list:
        candidates = by_title.get(task["title"], [])
        assert candidates, f"No se devolvió ninguna tarea con título {task['title']!r}"
        for field in _NULLABLE_FIELDS:
            if task[field] is None:
                # Al menos una de las tareas devueltas con ese título debe tener
                # el campo opcional como null (clave presente, valor nulo).
                assert any(c[field] is None for c in candidates), (
                    f"El campo opcional {field!r} nulo en almacenamiento no se "
                    f"serializó como null para la tarea {task['title']!r}"
                )
