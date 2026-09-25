"""Regresión de compatibilidad de los endpoints de sesión (feature: external-data-api).

Task 8.2 — Valida: Requisitos 5.6

Requisito 5.6: los endpoints existentes basados en sesión deben seguir
devolviendo, para peticiones idénticas, el mismo código de estado HTTP, el
mismo `Content-Type` y el mismo cuerpo de respuesta que antes de introducir la
API externa (`/api/v1/...`).

Como no existe un "snapshot" literal del antes, esta prueba fija el **contrato
estable** que estos endpoints de sesión siempre han cumplido y que la
introducción de la API externa no debe alterar:

- `/api/tasks`, `/api/work-tasks`, `/api/personal-tasks`:
  - Con sesión: 200, `Content-Type: application/json`, cuerpo = lista de tareas
    del usuario en sesión, cada una con las claves del contrato del módulo de
    tareas (`id, title, description, due_date, complexity, subject, created_at,
    user_id`) más los agregados `subtasks_total`/`subtasks_done`.
  - Sin sesión: 401 con cuerpo JSON `{"error": "No autorizado"}` (el
    `before_request` de cada módulo protege las rutas `/api/`).
- `/api/events`:
  - Con sesión: 200, `Content-Type: application/json`, cuerpo = lista de eventos
    del usuario con las claves `id, title, description, event_date, created_at,
    module, user_id`.
  - Sin sesión: 401 con cuerpo JSON `{"error": "No autorizado"}`.

La app de la fixture `client` ya tiene todos los blueprints registrados
(incluido `api_v1_bp`, cableado en la tarea 8.1), por lo que esta prueba se
ejercita contra la app real con el nuevo blueprint presente: confirma que su
presencia no cambia el comportamiento de los endpoints de sesión.
"""

from __future__ import annotations

from tests.strategies import (
    insert_event,
    insert_subtasks,
    insert_task,
    insert_user,
)

# Contrato de claves de cada tarea de sesión (`list_tasks` en `tasks_module`).
# Son las columnas de la tabla más los dos agregados calculados en la vista.
SESSION_TASK_KEYS = {
    "id",
    "title",
    "description",
    "due_date",
    "complexity",
    "subject",
    "created_at",
    "user_id",
    "subtasks_total",
    "subtasks_done",
}

# Contrato de claves de cada evento de sesión (`list_events` en `calendar_module`).
SESSION_EVENT_KEYS = {
    "id",
    "title",
    "description",
    "event_date",
    "created_at",
    "module",
    "user_id",
}

# Endpoint de lista de tareas por módulo de tareas.
TASK_ENDPOINTS = {
    "academic": "/api/tasks",
    "work": "/api/work-tasks",
    "personal": "/api/personal-tasks",
}


def _login(client, user_id):
    """Marca la sesión del cliente como autenticada para `user_id`."""
    with client.session_transaction() as s:
        s["user_id"] = user_id


def _seed_user_data(connection, user_id):
    """Siembra tareas (con subtareas) en los tres módulos y un par de eventos."""
    # Una tarea por módulo, con una subtarea completada y otra sin completar,
    # para ejercitar el cálculo de subtasks_total/subtasks_done.
    for module in ("academic", "work", "personal"):
        task = {
            "title": f"Tarea {module}",
            "description": None if module == "academic" else f"desc {module}",
            "due_date": "2026-05-01",
            "complexity": 3,
            "subject": f"Materia {module}",
            "created_at": "2026-04-01 10:00:00",
            "module": module,
        }
        task_id = insert_task(connection, user_id, task)
        insert_subtasks(
            connection,
            module,
            task_id,
            [
                {"title": "sub A", "completed": True},
                {"title": "sub B", "completed": False},
            ],
        )

    for i in range(2):
        insert_event(
            connection,
            user_id,
            {
                "title": f"Evento {i}",
                "description": None,
                "event_date": f"2026-05-0{i + 1}",
                "module": "general",
                "created_at": "2026-04-01 09:00:00",
            },
        )


# ---------------------------------------------------------------------------
# Comportamiento sin sesión (contrato preexistente: 401 JSON "No autorizado")
# ---------------------------------------------------------------------------


def test_session_task_endpoints_require_session(client):
    """Sin sesión, los endpoints de tareas responden 401 JSON como siempre."""
    for endpoint in TASK_ENDPOINTS.values():
        resp = client.get(endpoint)

        assert resp.status_code == 401, endpoint
        assert resp.mimetype == "application/json", endpoint
        body = resp.get_json()
        assert body == {"error": "No autorizado"}, endpoint


def test_session_events_endpoint_requires_session(client):
    """Sin sesión, `/api/events` responde 401 JSON como siempre."""
    resp = client.get("/api/events")

    assert resp.status_code == 401
    assert resp.mimetype == "application/json"
    assert resp.get_json() == {"error": "No autorizado"}


# ---------------------------------------------------------------------------
# Comportamiento con sesión (200, JSON, forma de cuerpo estable)
# ---------------------------------------------------------------------------


def test_session_task_endpoints_contract_with_session(client, connection):
    """Con sesión, cada endpoint de tareas mantiene su contrato de respuesta."""
    user_id = insert_user(connection, "regr_tasks")
    _seed_user_data(connection, user_id)
    _login(client, user_id)

    for module, endpoint in TASK_ENDPOINTS.items():
        resp = client.get(endpoint)

        # Mismo estado y tipo de contenido que siempre.
        assert resp.status_code == 200, endpoint
        assert resp.mimetype == "application/json", endpoint

        body = resp.get_json()
        # El elemento raíz es una lista (contrato de la vista list_tasks).
        assert isinstance(body, list), endpoint
        # Se sembró exactamente una tarea por módulo para este usuario.
        assert len(body) == 1, endpoint

        task = body[0]
        # Forma del cuerpo: exactamente las claves del contrato preexistente.
        assert set(task.keys()) == SESSION_TASK_KEYS, endpoint
        # Aislamiento por usuario (comportamiento existente sin cambios).
        assert task["user_id"] == user_id, endpoint
        # Agregados de subtareas calculados como siempre (2 totales, 1 hecha).
        assert task["subtasks_total"] == 2, endpoint
        assert task["subtasks_done"] == 1, endpoint


def test_session_events_endpoint_contract_with_session(client, connection):
    """Con sesión, `/api/events` mantiene su contrato de respuesta."""
    user_id = insert_user(connection, "regr_events")
    _seed_user_data(connection, user_id)
    _login(client, user_id)

    resp = client.get("/api/events")

    assert resp.status_code == 200
    assert resp.mimetype == "application/json"

    body = resp.get_json()
    assert isinstance(body, list)
    # Se sembraron dos eventos para este usuario.
    assert len(body) == 2

    for event in body:
        assert set(event.keys()) == SESSION_EVENT_KEYS
        assert event["user_id"] == user_id

    # Orden estable existente: ascendente por event_date.
    dates = [e["event_date"] for e in body]
    assert dates == sorted(dates)


def test_session_endpoints_return_empty_list_when_no_data(client, connection):
    """Con sesión y sin datos, los endpoints devuelven 200 y una lista vacía.

    Confirma que el contrato de "colección vacía" de los endpoints de sesión no
    cambia con la introducción de la API externa.
    """
    user_id = insert_user(connection, "regr_empty")
    _login(client, user_id)

    for endpoint in list(TASK_ENDPOINTS.values()) + ["/api/events"]:
        resp = client.get(endpoint)

        assert resp.status_code == 200, endpoint
        assert resp.mimetype == "application/json", endpoint
        assert resp.get_json() == [], endpoint
