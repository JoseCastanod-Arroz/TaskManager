"""Utilidades y fixtures compartidas de las pruebas (feature: external-data-api).

Objetivo: que cada prueba (unitaria o de propiedad) se ejecute contra una base
de datos SQLite temporal y aislada, inicializada con el mismo esquema que usa
la aplicación real, y disponer de un cliente de pruebas de Flask.

Detalles de diseño
------------------
- ``database.get_connection()`` lee ``database.DB_PATH`` en cada llamada, por lo
  que basta con reescribir ese atributo del módulo (monkeypatch) hacia un
  archivo temporal para redirigir toda la app (auth, tres módulos de tareas y
  calendario comparten la misma función) sin tocar la base real ``tasks.db``.
- Se usa un archivo temporal en disco (no ``:memory:``) porque la app abre y
  cierra una conexión nueva por operación; una base ``:memory:`` viviría sólo
  dentro de una conexión y no se compartiría entre llamadas.
- El orden de inicialización importa: primero ``init_auth_db`` (crea ``users`` y
  siembra un admin), del que dependen las migraciones ``user_id`` de los demás
  módulos, y la clave foránea de ``api_tokens``.
- ``init_api_tokens_db`` todavía no existe (lo crea la tarea 2.1). Se importa de
  forma tolerante: si aún no está, se omite sin romper el resto del entorno.
"""

import importlib
import sys
from pathlib import Path

import pytest

# Asegura que el paquete de la aplicación (raíz del proyecto) esté en el path
# de importación al ejecutar pytest desde cualquier directorio.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database  # noqa: E402


def _init_api_tokens_db_if_available():
    """Invoca ``init_api_tokens_db`` de ``auth`` si ya existe.

    Esta función la añade la tarea 2.1. Hasta entonces, el entorno de pruebas
    debe seguir funcionando, así que la importación es tolerante a su ausencia.
    """
    try:
        auth = importlib.import_module("auth")
    except Exception:  # pragma: no cover - la app siempre debería importar
        return
    init_fn = getattr(auth, "init_api_tokens_db", None)
    if callable(init_fn):
        init_fn()


def _init_all_schemas():
    """Crea todas las tablas sobre la base apuntada por ``database.DB_PATH``.

    Reproduce el orden de ``app.py`` (``__main__``): usuarios primero, luego los
    tres módulos de tareas, el calendario y, si está disponible, ``api_tokens``.
    """
    from auth import init_auth_db
    from calendar_module import init_calendar_db
    from app import academic_bp, work_bp, personal_bp

    init_auth_db()
    _init_api_tokens_db_if_available()
    academic_bp.init_db()
    work_bp.init_db()
    personal_bp.init_db()
    init_calendar_db()


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Redirige la base de datos a un archivo temporal e inicializa el esquema.

    Devuelve la ruta (``Path``) de la base temporal por si una prueba necesita
    inspeccionarla directamente. Cada prueba obtiene una base limpia y aislada.
    """
    db_file = tmp_path / "test_tasks.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    _init_all_schemas()
    yield db_file


@pytest.fixture()
def connection(temp_db):
    """Conexión SQLite abierta contra la base temporal ya inicializada.

    Se cierra automáticamente al terminar la prueba.
    """
    conn = database.get_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def app(temp_db):
    """Instancia de la aplicación Flask configurada para pruebas.

    Reutiliza el objeto ``app`` real (con todos los blueprints registrados) pero
    apuntando a la base temporal y en modo TESTING.
    """
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    """Cliente de pruebas de Flask para ejercitar los endpoints."""
    return app.test_client()
