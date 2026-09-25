"""Property 15: Content-Type y forma de la colección (feature: external-data-api).

Verifica que *toda respuesta exitosa* de recuperación de una colección de la API
externa (``GET /api/v1/tasks`` y ``GET /api/v1/events``) cumple simultáneamente:

- Estado HTTP 200.
- Encabezado ``Content-Type`` igual a ``application/json`` (``jsonify`` añade el
  charset, por lo que la comprobación es sobre el mimetype).
- El elemento raíz del cuerpo JSON es una **lista**, cuya longitud coincide con
  el número de recursos que satisfacen el filtro aplicado (lista vacía cuando no
  hay ninguno).

Notas de diseño de la prueba
----------------------------
- El blueprint ``api_v1_bp`` puede no estar cableado en ``app.py`` todavía; por
  eso la prueba monta una app Flask mínima y registra el blueprint. Queda
  enlazada a la base temporal porque ``get_connection`` lee ``database.DB_PATH``
  (reescrito por la fixture ``temp_db``) en cada llamada.
- La autenticación emite un token real con ``auth.generate_api_token(user_id)`` y
  lo presenta como ``Authorization: Bearer <raw>``.
- Se ejercitan ambos endpoints sin filtro y, además, con filtros **válidos**
  (``?module`` para tareas y ``?month`` para eventos) para cubrir varias
  respuestas exitosas sobre estados de datos aleatorios. Las longitudes
  esperadas se calculan a partir de los datos insertados.
"""

from __future__ import annotations

from collections import Counter

from flask import Flask
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api_module import api_v1_bp
from auth import generate_api_token
from database import get_connection
from tests.strategies import (
    EVENT_MODULES,
    MODULE_KEYS,
    events,
    insert_event,
    insert_task,
    insert_user,
    tasks,
)


def _build_api_app() -> Flask:
    """App Flask mínima con sólo ``api_v1_bp`` registrado.

    El registro es explícito porque el cableado en ``app.py`` es parte de otra
    tarea; así la prueba no depende de ese estado.
    """
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    flask_app.register_blueprint(api_v1_bp)
    return flask_app


def _assert_collection_ok(resp, expected_len):
    """Comprueba las tres condiciones de una respuesta de colección exitosa."""
    assert resp.status_code == 200
    # ``jsonify`` fija ``application/json`` (con charset); comparamos el mimetype.
    assert resp.mimetype == "application/json"
    assert resp.headers["Content-Type"].startswith("application/json")
    body = resp.get_json()
    assert isinstance(body, list)
    assert len(body) == expected_len


# Estado de datos aleatorio: cero o más tareas (con su módulo pineado) y cero o
# más eventos (con su módulo pineado). Permite listas vacías y repartos desiguales.
_task_with_module = st.sampled_from(MODULE_KEYS).flatmap(lambda m: tasks(module=m))
_event_with_module = st.sampled_from(EVENT_MODULES).flatmap(lambda m: events(module=m))


# Feature: external-data-api, Property 15: Content-Type y forma de la colección
# Valida: Requisitos 5.1, 5.2, 5.3
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    task_list=st.lists(_task_with_module, min_size=0, max_size=10),
    event_list=st.lists(_event_with_module, min_size=0, max_size=10),
)
def test_content_type_and_collection_shape(temp_db, task_list, event_list):
    app = _build_api_app()

    # --- Preparar estado de datos: usuario + tareas y eventos aleatorios ---
    conn = get_connection()
    user_id = insert_user(conn, "prop15")

    tasks_by_module = Counter(t["module"] for t in task_list)
    events_by_month = Counter()
    for task in task_list:
        insert_task(conn, user_id, task)
    for event in event_list:
        insert_event(conn, user_id, event)
        events_by_month[event["event_date"][:7]] += 1
    conn.close()

    # --- Autenticación por Token_API (Bearer) ---
    raw = generate_api_token(user_id)
    auth = {"Authorization": "Bearer " + raw}
    client = app.test_client()

    # --- Tareas: sin filtro (los tres módulos agregados) ---
    _assert_collection_ok(client.get("/api/v1/tasks", headers=auth), len(task_list))

    # --- Tareas: con filtro ?module válido (una respuesta por módulo) ---
    for module_key in MODULE_KEYS:
        resp = client.get(f"/api/v1/tasks?module={module_key}", headers=auth)
        _assert_collection_ok(resp, tasks_by_module[module_key])

    # --- Eventos: sin filtro (todos los del usuario) ---
    _assert_collection_ok(client.get("/api/v1/events", headers=auth), len(event_list))

    # --- Eventos: con filtro ?month válido para cada mes con datos ---
    for month, count in events_by_month.items():
        resp = client.get(f"/api/v1/events?month={month}", headers=auth)
        _assert_collection_ok(resp, count)
