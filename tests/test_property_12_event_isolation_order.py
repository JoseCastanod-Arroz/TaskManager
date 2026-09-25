"""Property 12: Aislamiento, serialización y orden de los eventos
(feature: external-data-api).

# Feature: external-data-api, Property 12: Aislamiento, serialización y orden de los eventos

Para todo conjunto de eventos pertenecientes a varios usuarios, la lista
devuelta por `GET /api/v1/events` a un `Token_API` válido contiene ÚNICAMENTE
eventos cuyo `user_id` coincide con el `Usuario_Propietario` del token (nunca
los de otro usuario), cada uno serializado con EXACTAMENTE las claves `id`,
`title`, `description`, `event_date`, `module` y `created_at`, y la lista está
ordenada de forma ascendente por `event_date` y, ante empate, de forma
ascendente por `id`.

**Validates: Requirements 4.1, 4.2, 4.3, 5.2**

Notas de diseño de la prueba
----------------------------
- El blueprint `api_v1_bp` todavía no se registra en `app.py` (eso ocurre en la
  tarea 8.1). Por eso, si la app de la fixture aún no lo tiene registrado, la
  prueba lo registra sobre la propia instancia antes de ejercitar el endpoint.
- La autenticación se hace emitiendo un token real con
  `auth.generate_api_token(user_id)` y enviándolo como
  `Authorization: Bearer <raw>`.
- Se generan varios usuarios y, para cada uno, varios eventos con `event_date`
  que puede repetir (empates de fecha) para ejercitar el desempate estable por
  `id`.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from auth import generate_api_token
from tests.strategies import events, insert_event, insert_user

# Claves EXACTAS que debe exponer cada evento serializado (Req 4.2).
_EVENT_KEYS = {"id", "title", "description", "event_date", "module", "created_at"}


def _ensure_api_v1_registered(flask_app):
    """Registra `api_v1_bp` en la app de pruebas si aún no está presente.

    El registro real en `app.py` es parte de una tarea posterior (8.1); para
    poder ejercitar el endpoint de forma aislada, lo registramos aquí de manera
    idempotente.
    """
    if "api_v1" not in flask_app.blueprints:
        from api_module import api_v1_bp

        flask_app.register_blueprint(api_v1_bp)


# Un usuario con su lista de eventos (0..6), cada evento con módulo/fecha
# arbitrarios.
_user_with_events = st.lists(events(), min_size=0, max_size=6)


# Feature: external-data-api, Property 12: Aislamiento, serialización y orden de los eventos
# Valida: Requisitos 4.1, 4.2, 4.3, 5.2
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(users_events=st.lists(_user_with_events, min_size=1, max_size=4))
def test_event_isolation_serialization_and_order(app, users_events):
    _ensure_api_v1_registered(app)

    from database import get_connection

    # Materializar usuarios y sus eventos. Para cada usuario recopilamos el
    # conjunto de ids de evento que le pertenecen y un mapa id -> datos
    # originales para verificar la serialización campo a campo.
    conn = get_connection()
    try:
        user_ids = []
        owner_event_ids = {}  # user_id -> set de id de evento
        event_data = {}  # id de evento -> dict de datos original
        for event_list in users_events:
            uid = insert_user(conn, "prop12")
            user_ids.append(uid)
            ids = set()
            for event in event_list:
                eid = insert_event(conn, uid, event)
                ids.add(eid)
                event_data[eid] = event
            owner_event_ids[uid] = ids
    finally:
        conn.close()

    client = app.test_client()

    # Para cada usuario, su token sólo debe devolver sus propios eventos, cada
    # uno con las claves exactas y en el orden esperado.
    for uid in user_ids:
        raw = generate_api_token(uid)
        resp = client.get(
            "/api/v1/events", headers={"Authorization": f"Bearer {raw}"}
        )

        assert resp.status_code == 200
        assert resp.is_json
        body = resp.get_json()
        assert isinstance(body, list)

        # Aislamiento: cada evento devuelto pertenece a este usuario y el
        # conjunto devuelto coincide EXACTAMENTE con lo insertado para él (no
        # falta ni sobra ninguno de otro usuario).
        expected_ids = owner_event_ids[uid]
        returned_ids = {e["id"] for e in body}
        assert returned_ids == expected_ids
        assert len(body) == len(expected_ids)

        for item in body:
            # Serialización: claves EXACTAS, sin sobrar ni faltar ninguna.
            assert set(item.keys()) == _EVENT_KEYS

            # Cada campo coincide con el dato original insertado.
            original = event_data[item["id"]]
            assert item["title"] == original["title"]
            assert item["description"] == original["description"]
            assert item["event_date"] == original["event_date"]
            assert item["module"] == original["module"]
            assert item["created_at"] == original["created_at"]

        # Orden: la lista está ordenada ascendente por `event_date` y, ante
        # empate, ascendente por `id`.
        order = [(e["event_date"], e["id"]) for e in body]
        assert order == sorted(order)
