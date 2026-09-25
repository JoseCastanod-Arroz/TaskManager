"""Property 14: Mes con formato no válido (feature: external-data-api).

# Feature: external-data-api, Property 14: Mes con formato no válido

Valida que, para toda cadena de mes con un formato distinto del estricto
`YYYY-MM` con mes 01–12, la petición ``GET /api/v1/events?month=<invalido>``
responde 400 con un cuerpo JSON que incluye ``error`` y **no** devuelve ningún
evento (Req 4.7).

**Validates: Requirements 4.7**

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.

Diseño de la prueba
-------------------
- Se genera una batería de cadenas de mes *no válidas* con Hypothesis: meses
  fuera de rango (``2026-13``, ``2026-00``), sin cero de relleno (``2026-5``),
  con día extra (``2026-05-01``), texto arbitrario (``abc``), cadena vacía
  (``""``) y ruido general. Un filtro descarta cualquier cadena que por azar
  cumpla el patrón válido, garantizando que todas las entradas son inválidas.
- Se puebla la base con eventos válidos del ``Usuario_Propietario`` para
  comprobar que, pese a existir eventos, una petición con mes inválido no
  devuelve ninguno (se rechaza antes de tocar la base).
- Se ejercita el endpoint real vía el cliente de pruebas de Flask,
  autenticando con ``generate_api_token(user_id)`` + encabezado Bearer.
"""

from __future__ import annotations

import re

from flask import Flask
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api_module import api_v1_bp
from auth import generate_api_token
from database import get_connection
from tests.strategies import events, insert_event, insert_user

# Mismo patrón estricto que usa el endpoint: `YYYY-MM`. Se usa aquí solo para
# filtrar y garantizar que las entradas generadas son realmente inválidas.
_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def _is_valid_month(value: str) -> bool:
    """Replica la validación del endpoint: `YYYY-MM` con mes 01–12."""
    if not _MONTH_PATTERN.match(value):
        return False
    return 1 <= int(value[5:7]) <= 12


def _make_api_app():
    """App Flask mínima con solo ``api_v1_bp`` registrado.

    El blueprint se registra explícitamente porque el cableado en ``app.py``
    (tarea 8.1) aún no existe. La app queda ligada a la base temporal a través
    de ``database.DB_PATH`` (redirigido por la fixture ``temp_db``), ya que
    ``get_connection()`` lee ese atributo en cada llamada.
    """
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    flask_app.register_blueprint(api_v1_bp)
    return flask_app


# ---------- Estrategia de cadenas de mes NO válidas ----------

# Casos "duros" (siempre inválidos) fijados explícitamente para asegurar que el
# espacio incluye los ejemplos representativos del criterio de aceptación.
_hard_invalid = st.sampled_from(
    [
        "2026-13",     # mes fuera de rango (> 12)
        "2026-00",     # mes fuera de rango (00)
        "2026-5",      # sin cero de relleno
        "2026-05-01",  # componente de día extra
        "abc",         # texto arbitrario
        "",            # cadena vacía
        "2026/05",     # separador incorrecto
        "202605",      # sin separador
        "26-05",       # año de dos dígitos
        "2026-5a",     # dígito + letra
        " 2026-05",    # espacio inicial
        "2026-05 ",    # espacio final
        "2026-15",     # mes fuera de rango
    ]
)

# Generador amplio de ruido: cualquier texto imprimible corto.
_noise = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF, blacklist_categories=("Cs",)),
    min_size=0,
    max_size=12,
)

# Generador estructurado: `YYYY-MM` con componentes potencialmente inválidos
# (mes 0 o > 12, año de longitud variable), para cubrir el borde del patrón.
_structured = st.builds(
    lambda y, m: f"{y}-{m}",
    st.integers(min_value=0, max_value=99999).map(str),
    st.integers(min_value=0, max_value=99).map(str),  # sin relleno -> a veces 1 dígito
)

# Unión de estrategias, filtrando cualquier cadena que resulte válida por azar.
invalid_months = st.one_of(_hard_invalid, _noise, _structured).filter(
    lambda s: not _is_valid_month(s)
)


# Feature: external-data-api, Property 14: Mes con formato no válido
# Valida: Requisitos 4.7
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(month=invalid_months, event_list=st.lists(events(), min_size=0, max_size=6))
def test_event_invalid_month(temp_db, month, event_list):
    app = _make_api_app()

    # --- Preparar estado de datos: usuario + eventos válidos ---
    conn = get_connection()
    user_id = insert_user(conn, "prop14")
    for event in event_list:
        insert_event(conn, user_id, event)
    conn.close()

    # --- Autenticación por Token_API (Bearer) ---
    raw = generate_api_token(user_id)
    auth = {"Authorization": "Bearer " + raw}
    client = app.test_client()

    # --- Petición con mes inválido: 400, cuerpo con `error`, sin eventos ---
    resp = client.get("/api/v1/events", query_string={"month": month}, headers=auth)

    assert resp.status_code == 400
    assert resp.mimetype == "application/json"

    body = resp.get_json()
    assert isinstance(body, dict)
    assert "error" in body

    # No se devuelve ninguna lista de eventos: el cuerpo es el sobre de error,
    # nunca una colección.
    assert not isinstance(body, list)
    assert "events" not in body
