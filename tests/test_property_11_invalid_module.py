"""Property 11: Módulo de tareas no válido (feature: external-data-api).

# Feature: external-data-api, Property 11: Módulo de tareas no válido

Valida que, para toda cadena de módulo distinta de ``academic``, ``work`` y
``personal``, la petición ``GET /api/v1/tasks?module=<invalido>`` responde con
estado HTTP 400 y un cuerpo JSON que incluye la clave ``error``, sin devolver
ninguna tarea (Req 3.9).

**Validates: Requirements 3.9**

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.

Diseño de la prueba
-------------------
- Se genera una cadena de módulo *no válida*: cualquier texto que no pertenezca
  al conjunto ``{academic, work, personal}`` (se incluye la cadena vacía y
  textos arbitrarios, filtrando los tres valores válidos).
- Se siembra estado de datos real (algunas tareas del usuario en los tres
  módulos) para comprobar que, aun existiendo tareas, un módulo inválido no
  devuelve ninguna.
- Se ejercita el endpoint real a través del cliente de pruebas de Flask,
  autenticando con ``generate_api_token(user_id)`` + encabezado Bearer.
- Se comprueba: estado 400, ``Content-Type`` JSON, el cuerpo es un objeto con la
  clave ``error``, y no se devuelve ninguna lista de tareas.
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
    aún no forma parte de esta prueba. La app queda ligada a la base temporal a
    través de ``database.DB_PATH`` (redirigido por la fixture ``temp_db``), ya
    que ``get_connection()`` lee ese atributo en cada llamada.
    """
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    flask_app.register_blueprint(api_v1_bp)
    return flask_app


_VALID_MODULES = set(MODULE_KEYS)

# Estrategia: cadenas de módulo NO válidas. Cubre texto imprimible arbitrario
# (incluida la cadena vacía) y filtra los tres valores válidos para garantizar
# que la entrada siempre está fuera del conjunto aceptado.
_invalid_modules = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF, blacklist_categories=("Cs",)),
    min_size=0,
    max_size=40,
).filter(lambda s: s not in _VALID_MODULES)


# Feature: external-data-api, Property 11: Módulo de tareas no válido
# Valida: Requisito 3.9
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(module=_invalid_modules)
def test_invalid_module(temp_db, module):
    app = _make_api_app()

    # --- Preparar estado de datos: usuario + al menos una tarea por módulo ---
    # Sembrar tareas reales asegura que un módulo inválido no devuelve tareas
    # "por casualidad" (base vacía), sino porque la petición se rechaza.
    conn = get_connection()
    user_id = insert_user(conn, "prop11")
    for module_key in MODULE_KEYS:
        insert_task(
            conn,
            user_id,
            {
                "title": "t",
                "description": None,
                "due_date": None,
                "complexity": 1,
                "subject": "s",
                "created_at": "2024-01-01 00:00:00",
                "module": module_key,
            },
        )
    conn.close()

    # --- Autenticación por Token_API (Bearer) ---
    raw = generate_api_token(user_id)
    headers = {"Authorization": "Bearer " + raw}
    client = app.test_client()

    resp = client.get("/api/v1/tasks", query_string={"module": module}, headers=headers)

    # Estado 400 ante un módulo no válido (Req 3.9).
    assert resp.status_code == 400

    # El sobre de error es JSON e incluye la clave ``error``.
    assert resp.mimetype == "application/json"
    body = resp.get_json()
    assert isinstance(body, dict)
    assert "error" in body

    # No se devuelve ninguna tarea: el cuerpo es el sobre de error, no una lista.
    assert not isinstance(body, list)
    assert "tasks" not in body
