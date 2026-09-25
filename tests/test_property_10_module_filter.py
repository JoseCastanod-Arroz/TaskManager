"""Property 10: Filtrado de tareas por módulo (feature: external-data-api).

# Feature: external-data-api, Property 10: Filtrado de tareas por módulo

Valida que, para todo estado de datos:

- Si la petición especifica un ``Modulo_Tareas`` válido (``academic``, ``work``
  o ``personal``), *todas* las tareas devueltas por ``GET /api/v1/tasks?module=<valido>``
  pertenecen a ese módulo (Req 3.6).
- Si la petición no especifica módulo, el conjunto devuelto es exactamente la
  unión de las tareas del usuario en los tres módulos (Req 3.7).

**Validates: Requirements 3.6, 3.7**

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.

Diseño de la prueba
-------------------
- Se genera una lista de tareas con el módulo *pineado* (usando el composite
  ``tasks(module=...)``) de modo que el estado de datos cubra los tres módulos
  con recuentos arbitrarios (incluido 0).
- Se inserta cada tarea para el ``Usuario_Propietario`` (resuelto por su token).
- Se ejercita el endpoint real a través del cliente de pruebas de Flask,
  autenticando con ``generate_api_token(user_id)`` + encabezado Bearer.
- Se comprueba (a) el conjunto sin filtro = unión de los tres módulos, y (b) por
  cada módulo válido, que toda tarea devuelta lleva ese módulo y que el conjunto
  de ids coincide con las tareas insertadas en ese módulo.
"""

from __future__ import annotations

from flask import Flask
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api_module import api_v1_bp
from auth import generate_api_token
from database import get_connection
from tests.strategies import MODULE_KEYS, insert_task, insert_user, tasks


def _make_api_app():
    """App Flask mínima con sólo ``api_v1_bp`` registrado.

    El blueprint se registra explícitamente porque el cableado en ``app.py``
    (tarea 8.1) aún no existe. La app queda ligada a la base temporal a través
    de ``database.DB_PATH`` (redirigido por la fixture ``temp_db``), ya que
    ``get_connection()`` lee ese atributo en cada llamada.
    """
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    flask_app.register_blueprint(api_v1_bp)
    return flask_app


# Estrategia: una lista de 0..12 tareas, cada una con su módulo pineado a uno de
# los tres válidos. Al pinear el módulo dentro del composite garantizamos un
# reparto arbitrario (posiblemente desigual, incluido vacío) entre módulos, que
# es justo el estado de datos que ejercita el filtrado.
_task_with_module = st.sampled_from(MODULE_KEYS).flatmap(
    lambda m: tasks(module=m)
)
_task_lists = st.lists(_task_with_module, min_size=0, max_size=12)


# Feature: external-data-api, Property 10: Filtrado de tareas por módulo
# Valida: Requisitos 3.6, 3.7
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(task_list=_task_lists)
def test_module_filter(temp_db, task_list):
    app = _make_api_app()

    # --- Preparar estado de datos: usuario + tareas repartidas por módulo ---
    conn = get_connection()
    user_id = insert_user(conn, "prop10")

    # Mapa módulo -> conjunto de ids de tareas insertadas para ese módulo.
    ids_by_module = {key: set() for key in MODULE_KEYS}
    for task in task_list:
        task_id = insert_task(conn, user_id, task)
        ids_by_module[task["module"]].add(task_id)
    conn.close()

    expected_all_ids = set().union(*ids_by_module.values()) if ids_by_module else set()

    # --- Autenticación por Token_API (Bearer) ---
    raw = generate_api_token(user_id)
    auth = {"Authorization": "Bearer " + raw}
    client = app.test_client()

    # --- (b) Filtro por cada módulo válido ---
    for module_key in MODULE_KEYS:
        resp = client.get(f"/api/v1/tasks?module={module_key}", headers=auth)
        assert resp.status_code == 200
        returned = resp.get_json()
        assert isinstance(returned, list)

        # Toda tarea devuelta pertenece al módulo solicitado (Req 3.6).
        for t in returned:
            assert t["module"] == module_key

        # El conjunto de ids devueltos coincide exactamente con lo insertado.
        returned_ids = {t["id"] for t in returned}
        assert returned_ids == ids_by_module[module_key]

    # --- (a) Sin filtro: unión de los tres módulos (Req 3.7) ---
    resp_all = client.get("/api/v1/tasks", headers=auth)
    assert resp_all.status_code == 200
    all_returned = resp_all.get_json()
    assert isinstance(all_returned, list)

    # Cada tarea devuelta pertenece a uno de los tres módulos válidos.
    for t in all_returned:
        assert t["module"] in MODULE_KEYS

    # El conjunto devuelto es exactamente la unión de las tareas del usuario en
    # los tres módulos.
    all_returned_ids = {t["id"] for t in all_returned}
    assert all_returned_ids == expected_all_ids
