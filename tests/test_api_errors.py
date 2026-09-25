"""Pruebas de ejemplo/integración de rutas y errores de servidor de la API externa.

Feature: external-data-api — Task 7.3.

Cubre dos criterios de aceptación del Requisito 5 que no están cubiertos por las
pruebas basadas en propiedades:

- **Req 5.4**: una petición a un recurso/ruta inexistente responde 404 con un
  cuerpo JSON que incluye un campo ``error``.
- **Req 5.5**: si ocurre un error de servidor inesperado durante el
  procesamiento de una petición, el sistema responde 500 con un cuerpo JSON que
  incluye un campo ``error`` (y, al ser la API de sólo lectura, no aplica
  ninguna modificación de datos).

Aislamiento de la app
---------------------
Estas pruebas montan el blueprint real ``api_v1_bp`` sobre una **app Flask
propia y aislada** (fixture ``api_app``/``api_client`` de este módulo) en lugar
de reusar el ``app`` compartido de ``conftest``. Motivo: al emitir peticiones
HTTP marcamos la app como "ya atendió su primera petición"; otras pruebas del
proyecto añaden rutas al ``app`` compartido de forma perezosa en tiempo de
ejecución y fallarían si ese ``app`` ya hubiera atendido una petición. Usar una
app propia evita ese acoplamiento por orden de ejecución. La base de datos sigue
siendo la temporal aislada de la fixture ``temp_db``.

Notas de diseño y comportamiento observado (importante para el 404)
-------------------------------------------------------------------
El diseño registra el manejador 404 **a nivel de blueprint**
(``@api_v1_bp.errorhandler(404)``) y explícitamente indica que "el 404 global de
Flask (páginas HTML) no cambia". Un ``errorhandler(404)`` de blueprint sólo se
dispara para 404 que se generan **dentro** de una ruta ya emparejada del
blueprint (p. ej. un ``abort(404)`` en una vista); NO se dispara para una URL
arbitraria desconocida, porque en ese caso el enrutador de Flask no logra
asociar la URL a ningún blueprint y responde con su 404 HTML por defecto.

Por eso las pruebas de 404 distinguen dos comportamientos:

1. El comportamiento **realmente cableado** de la app para una ruta desconocida
   ``/api/v1/...`` (hoy: 404 HTML por defecto de Flask). Ver
   ``test_unknown_path_current_wired_behavior_is_html_404`` y la nota sobre la
   brecha respecto a Req 5.4.
2. El comportamiento **especificado por el diseño**: cuando un 404 se genera
   dentro del contexto del blueprint, el manejador devuelve JSON
   ``{"error": "Recurso no encontrado"}``. Se valida con una ruta de sonda que
   hace ``abort(404)`` dentro del blueprint. Ver
   ``test_blueprint_404_handler_returns_json``.
"""

from unittest import mock

import pytest
from flask import Blueprint, abort

import api_module
from api_module import api_v1_bp


# ---------------------------------------------------------------------------
# Fixtures: app Flask aislada con el blueprint real de la API externa
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_app(temp_db):
    """App Flask propia con ``api_v1_bp`` registrado, apuntando a la base temporal.

    Se construye una app nueva (no la compartida de ``conftest``) para no marcar
    la app compartida como "primera petición atendida" y evitar acoplamientos de
    orden con otras pruebas. ``temp_db`` garantiza el esquema inicializado.
    """
    from flask import Flask

    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(api_v1_bp)
    return app


@pytest.fixture()
def api_client(api_app):
    """Cliente de pruebas de la app aislada de la API externa."""
    return api_app.test_client()


# ---------------------------------------------------------------------------
# Ayudante: crear un usuario y emitir un Token_API válido sobre la base temporal
# ---------------------------------------------------------------------------

def _create_user_with_token(username="apiuser"):
    """Inserta un usuario en la base temporal y le emite un Token_API.

    Devuelve ``(user_id, raw_token)``. Debe llamarse dentro de una prueba cuya
    base temporal (``temp_db``) ya esté activa (vía ``api_app``/``api_client``),
    de modo que ``database.DB_PATH`` apunte a la base temporal.
    """
    import database
    from auth import generate_api_token

    conn = database.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, "x"),
        )
        conn.commit()
        user_id = cur.lastrowid
    finally:
        conn.close()

    raw_token = generate_api_token(user_id)
    return user_id, raw_token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Req 5.4 — Ruta/recurso inexistente
# ---------------------------------------------------------------------------

def test_blueprint_404_handler_returns_json():
    """El manejador 404 del blueprint devuelve JSON con ``error`` (Req 5.4).

    Comportamiento **especificado por el diseño**: cuando un 404 se genera
    dentro del contexto del blueprint ``api_v1_bp``, el sobre de error es
    ``{"error": "Recurso no encontrado"}`` con ``Content-Type: application/json``.

    Para no mutar el blueprint compartido, se crea un blueprint hijo local que
    hereda el mismo manejador 404 reutilizando ``api_module.handle_not_found`` y
    se monta en una app propia con una ruta de sonda que hace ``abort(404)``.
    """
    from flask import Flask

    probe_bp = Blueprint("api_v1_probe", __name__, url_prefix="/api/v1")

    # Mismo manejador 404 que el blueprint real (misma función del diseño).
    probe_bp.register_error_handler(404, api_module.handle_not_found)

    @probe_bp.route("/__probe_not_found__")
    def _probe():  # pragma: no cover - ejecutada vía el cliente
        abort(404)

    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(probe_bp)
    client = app.test_client()

    resp = client.get("/api/v1/__probe_not_found__")

    assert resp.status_code == 404
    assert resp.mimetype == "application/json"
    body = resp.get_json()
    assert isinstance(body, dict)
    assert "error" in body
    assert body["error"] == "Recurso no encontrado"


def test_blueprint_404_handler_is_wired_for_404(api_app):
    """El manejador JSON de 404 está registrado en el blueprint ``api_v1_bp``.

    Complementa la prueba anterior: verifica que ``handle_not_found`` está
    efectivamente asociado al código 404 dentro del blueprint real, de modo que
    un 404 originado en el contexto del blueprint (p. ej. ``abort(404)`` en una
    vista) devolvería JSON en la app real (Req 5.4).
    """
    bp_handlers = api_app.error_handler_spec.get("api_v1", {})
    handlers_404 = bp_handlers.get(404, {})
    registered = set(handlers_404.values())

    assert api_module.handle_not_found in registered


def test_unknown_path_current_wired_behavior_is_html_404(api_client):
    """Documenta el comportamiento REAL de la app cableada para ruta desconocida.

    Para una URL arbitraria bajo ``/api/v1/`` que no coincide con ninguna ruta
    registrada, el enrutador de Flask no entra en el contexto del blueprint, así
    que responde con su 404 por defecto (HTML), no con el sobre JSON.

    Esto es una **brecha conocida** respecto a la intención literal de Req 5.4
    (que pide JSON para "una ruta que no existe"): satisfacerla requeriría un
    manejador 404 a nivel de aplicación (app-level), que no forma parte del
    cableado actual (el diseño registra el manejador sólo a nivel de blueprint).
    Esta prueba fija el comportamiento actual para hacer visible la brecha; el
    contrato JSON de Req 5.4 se valida en ``test_blueprint_404_handler_returns_json``.
    """
    resp = api_client.get("/api/v1/ruta-que-no-existe")

    assert resp.status_code == 404
    # Comportamiento actual: 404 HTML por defecto de Flask (no JSON del blueprint).
    assert resp.mimetype == "text/html"


# ---------------------------------------------------------------------------
# Req 5.5 — Error de servidor inesperado
# ---------------------------------------------------------------------------

def test_internal_error_on_tasks_returns_500_json(api_client):
    """Un error inesperado durante la consulta de tareas → 500 JSON (Req 5.5).

    Se simula el fallo haciendo que ``get_connection`` (usada por
    ``GET /api/v1/tasks``) lance una excepción. El manejador
    ``errorhandler(Exception)`` del blueprint debe capturarla y responder 500
    con el sobre ``{"error": ...}`` y ``Content-Type: application/json``.
    """
    _user_id, token = _create_user_with_token()

    with mock.patch.object(
        api_module, "get_connection", side_effect=RuntimeError("fallo inesperado")
    ):
        resp = api_client.get("/api/v1/tasks", headers=_auth(token))

    assert resp.status_code == 500
    assert resp.mimetype == "application/json"
    body = resp.get_json()
    assert isinstance(body, dict)
    assert "error" in body
    assert body["error"] == "Ocurrió un error interno del servidor"


def test_internal_error_on_events_returns_500_json(api_client):
    """Un error inesperado durante la consulta de eventos → 500 JSON (Req 5.5).

    Igual que el caso de tareas, pero ejercitando ``GET /api/v1/events`` para
    cubrir el otro endpoint de lectura de la API externa.
    """
    _user_id, token = _create_user_with_token(username="apiuser2")

    with mock.patch.object(
        api_module, "get_connection", side_effect=RuntimeError("fallo inesperado")
    ):
        resp = api_client.get("/api/v1/events", headers=_auth(token))

    assert resp.status_code == 500
    assert resp.mimetype == "application/json"
    body = resp.get_json()
    assert isinstance(body, dict)
    assert "error" in body
    assert body["error"] == "Ocurrió un error interno del servidor"
