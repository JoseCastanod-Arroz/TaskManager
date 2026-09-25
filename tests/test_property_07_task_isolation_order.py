"""Property 7: Aislamiento y orden de las tareas por propietario
(feature: external-data-api).

# Feature: external-data-api, Property 7: Aislamiento y orden de las tareas por propietario

Para todo conjunto de tareas pertenecientes a varios usuarios repartidas entre
los tres módulos (`academic`, `work`, `personal`), la lista devuelta por
`GET /api/v1/tasks` a un `Token_API` válido contiene ÚNICAMENTE tareas cuyo
`user_id` coincide con el `Usuario_Propietario` del token (nunca las de otro
usuario), y la lista agregada está ordenada de forma ascendente por
`created_at` y, ante empate, de forma ascendente por `id`.

**Validates: Requirements 3.1, 5.2**

Notas de diseño de la prueba
----------------------------
- El blueprint `api_v1_bp` todavía no se registra en `app.py` (eso ocurre en la
  tarea 8.1). Por eso, si la app de la fixture aún no lo tiene registrado, la
  prueba lo registra sobre la propia instancia antes de ejercitar el endpoint.
- La autenticación se hace emitiendo un token real con
  `auth.generate_api_token(user_id)` y enviándolo como
  `Authorization: Bearer <raw>`.
- Se generan varios usuarios y, para cada uno, varias tareas en módulos
  arbitrarios con `created_at` que puede repetir (empates) para ejercitar el
  desempate estable por `id`.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from auth import generate_api_token
from tests.strategies import insert_task, insert_user, tasks


def _ensure_api_v1_registered(flask_app):
    """Registra `api_v1_bp` en la app de pruebas si aún no está presente.

    El registro real en `app.py` es parte de una tarea posterior (8.1); para
    poder ejercitar el endpoint de forma aislada, lo registramos aquí de manera
    idempotente.
    """
    if "api_v1" not in flask_app.blueprints:
        from api_module import api_v1_bp

        flask_app.register_blueprint(api_v1_bp)


# Un usuario con su lista de tareas (0..6), cada tarea en un módulo arbitrario.
_user_with_tasks = st.lists(tasks(), min_size=0, max_size=6)


# Feature: external-data-api, Property 7: Aislamiento y orden de las tareas por propietario
# Valida: Requisitos 3.1, 5.2
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(users_tasks=st.lists(_user_with_tasks, min_size=1, max_size=4))
def test_task_isolation_and_order(app, users_tasks):
    _ensure_api_v1_registered(app)

    from database import get_connection

    # Materializar usuarios y sus tareas. `owner_task_ids` recopila, para cada
    # usuario, el conjunto de (id de tarea, módulo) que le pertenecen.
    conn = get_connection()
    try:
        user_ids = []
        owner_task_keys = {}  # user_id -> set de (module, task_id)
        for task_list in users_tasks:
            uid = insert_user(conn, "prop7")
            user_ids.append(uid)
            keys = set()
            for task in task_list:
                tid = insert_task(conn, uid, task)
                keys.add((task["module"], tid))
            owner_task_keys[uid] = keys
    finally:
        conn.close()

    client = app.test_client()

    # Para cada usuario, su token sólo debe devolver sus propias tareas y en el
    # orden agregado esperado.
    for uid in user_ids:
        raw = generate_api_token(uid)
        resp = client.get(
            "/api/v1/tasks", headers={"Authorization": f"Bearer {raw}"}
        )

        assert resp.status_code == 200
        assert resp.is_json
        body = resp.get_json()
        assert isinstance(body, list)

        # Aislamiento: cada tarea devuelta pertenece a este usuario (coincide
        # con alguno de los (module, id) insertados para él) y el número total
        # coincide exactamente con lo insertado (no falta ni sobra ninguna).
        expected_keys = owner_task_keys[uid]
        returned_keys = {(t["module"], t["id"]) for t in body}
        assert returned_keys == expected_keys
        assert len(body) == len(expected_keys)

        # Orden: la lista agregada está ordenada ascendente por `created_at` y,
        # ante empate, ascendente por `id`.
        order = [(t["created_at"], t["id"]) for t in body]
        assert order == sorted(order)
