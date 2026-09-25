"""Property 13: Filtrado de eventos por mes (feature: external-data-api).

# Feature: external-data-api, Property 13: Filtrado de eventos por mes

Valida que, para todo mes en formato ``YYYY-MM`` válido, *todos* los eventos
devueltos por ``GET /api/v1/events?month=YYYY-MM`` tienen una ``event_date`` que
pertenece a ese mes; y que la lista es vacía cuando ningún evento del
``Usuario_Propietario`` cae en ese mes (Req 4.4).

**Validates: Requirements 4.4**

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.

Diseño de la prueba
-------------------
- Se genera una lista de eventos con ``event_date`` en varios meses (los
  generadores de ``strategies`` producen fechas ``YYYY-MM-DD`` con empates de
  mes), que se insertan para el ``Usuario_Propietario`` (resuelto por su token).
- Se ejercita el endpoint real a través del cliente de pruebas de Flask,
  autenticando con ``generate_api_token(user_id)`` + encabezado Bearer.
- Como el mes se deriva de las ``event_date`` insertadas (``YYYY-MM``), la
  consulta con ese mes debe devolver exactamente los eventos de ese mes: se
  comprueba (a) que toda ``event_date`` devuelta empieza por ``<month>-``, y (b)
  que el conjunto de ids devueltos coincide con los eventos insertados en ese
  mes.
- Se comprueba además que un mes válido sin eventos devuelve una lista vacía.
"""

from __future__ import annotations

from collections import defaultdict

from flask import Flask
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api_module import api_v1_bp
from auth import generate_api_token
from database import get_connection
from tests.strategies import events, insert_event, insert_user


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


# Estrategia: una lista de 0..12 eventos. Sus ``event_date`` cubren varios meses
# (con empates), que es justo el estado de datos que ejercita el filtrado.
_event_lists = st.lists(events(), min_size=0, max_size=12)


# Feature: external-data-api, Property 13: Filtrado de eventos por mes
# Valida: Requisitos 4.4
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(event_list=_event_lists)
def test_event_month_filter(temp_db, event_list):
    app = _make_api_app()

    # --- Preparar estado de datos: usuario + eventos repartidos por mes ---
    conn = get_connection()
    user_id = insert_user(conn, "prop13")

    # Mapa mes (YYYY-MM) -> conjunto de ids de eventos insertados en ese mes.
    ids_by_month = defaultdict(set)
    for event in event_list:
        event_id = insert_event(conn, user_id, event)
        month = event["event_date"][:7]  # YYYY-MM
        ids_by_month[month].add(event_id)
    conn.close()

    # --- Autenticación por Token_API (Bearer) ---
    raw = generate_api_token(user_id)
    auth = {"Authorization": "Bearer " + raw}
    client = app.test_client()

    # --- Para cada mes presente: todos los eventos devueltos son de ese mes ---
    for month, expected_ids in ids_by_month.items():
        resp = client.get(f"/api/v1/events?month={month}", headers=auth)
        assert resp.status_code == 200
        returned = resp.get_json()
        assert isinstance(returned, list)

        # (a) Toda event_date devuelta pertenece al mes solicitado (Req 4.4).
        for ev in returned:
            assert ev["event_date"][:7] == month
            assert ev["event_date"].startswith(month + "-")

        # (b) El conjunto de ids devueltos coincide exactamente con lo insertado
        # en ese mes (no faltan ni sobran eventos del propietario).
        returned_ids = {ev["id"] for ev in returned}
        assert returned_ids == expected_ids

    # --- Mes válido sin eventos -> lista vacía ---
    # "2099-12" queda fuera del rango de fechas generadas (2024-2026), por lo que
    # ningún evento insertado cae en ese mes.
    empty_resp = client.get("/api/v1/events?month=2099-12", headers=auth)
    assert empty_resp.status_code == 200
    assert empty_resp.get_json() == []
