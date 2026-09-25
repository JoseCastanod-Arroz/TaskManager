"""Prueba de propiedad 9 (feature: external-data-api).

Inclusión y orden de subtareas: para toda `Tarea` devuelta por
`GET /api/v1/tasks`, su clave `subtasks` es una lista (vacía si la tarea no
tiene subtareas) en la que cada subtarea expone exactamente `id`, `title` y
`completed` (booleano), y las subtareas están ordenadas de forma ascendente
por `id`.

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.

El blueprint `api_v1_bp` aún no está cableado en `app.py` (eso es la tarea
8.1), así que la prueba monta una app Flask mínima y le registra el blueprint,
apuntando a la misma base temporal que preparan las fixtures de `conftest`.
"""

from flask import Flask
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api_module import api_v1_bp
from auth import generate_api_token
from tests.strategies import (
    MODULE_KEYS,
    insert_subtasks,
    insert_task,
    insert_user,
    subtasks,
    tasks,
)


def _make_client():
    """App Flask mínima con el blueprint de la API externa registrado."""
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    flask_app.register_blueprint(api_v1_bp)
    return flask_app.test_client()


# Cada elemento es (tarea, lista_de_subtareas) para una misma tarea.
_task_with_subs = st.tuples(tasks(), subtasks(max_count=5))


# Feature: external-data-api, Property 9: Inclusión y orden de subtareas
# Valida: Requisitos 3.4, 3.5
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(data=st.lists(_task_with_subs, min_size=0, max_size=6))
def test_subtask_inclusion_and_order(connection, data):
    # Un usuario dueño y su Token_API.
    user_id = insert_user(connection, username="owner")
    raw = generate_api_token(user_id)

    # Materializar tareas y subtareas, registrando el orden de inserción.
    # Mapa: (module, task_id) -> lista de ids de subtarea en orden de inserción.
    inserted_subtask_ids = {}
    for task, subtask_list in data:
        module = task["module"]
        task_id = insert_task(connection, user_id, task)
        ids = insert_subtasks(connection, module, task_id, subtask_list)
        inserted_subtask_ids[(module, task_id)] = (ids, subtask_list)

    client = _make_client()
    resp = client.get("/api/v1/tasks", headers={"Authorization": "Bearer " + raw})

    assert resp.status_code == 200
    returned = resp.get_json()
    assert isinstance(returned, list)

    for returned_task in returned:
        subs = returned_task["subtasks"]

        # `subtasks` siempre es una lista (Req 3.5).
        assert isinstance(subs, list)

        # Cada subtarea expone exactamente id, title y completed (Req 3.4).
        for sub in subs:
            assert set(sub.keys()) == {"id", "title", "completed"}
            assert isinstance(sub["id"], int)
            assert isinstance(sub["title"], str)
            assert isinstance(sub["completed"], bool)

        # Están ordenadas ascendentemente por id (Req 3.4).
        ids = [s["id"] for s in subs]
        assert ids == sorted(ids)

        # La lista coincide en cantidad y contenido con lo insertado para esa
        # tarea concreta (incluye el caso vacío -> [] de Req 3.5).
        key = (returned_task["module"], returned_task["id"])
        expected_ids, expected_subs = inserted_subtask_ids[key]

        assert ids == sorted(expected_ids)

        # `completed` normalizado de 0/1 a booleano, emparejando por id ASC el
        # orden de inserción con el de los datos generados.
        expected_by_id = dict(zip(expected_ids, expected_subs))
        for sub in subs:
            original = expected_by_id[sub["id"]]
            assert sub["title"] == original["title"]
            assert sub["completed"] is bool(original["completed"])

    # Toda tarea del usuario aparece con su clave subtasks presente.
    assert len(returned) == len(data)
