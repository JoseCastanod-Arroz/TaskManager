"""Pruebas de ejemplo/integración de emisión y revocación del Token_API.

Feature: external-data-api — Tarea 4.2.

Cubren los requisitos no cubiertos por propiedades relativos a la gestión del
token por sesión:

- Emisión/revocación sin sesión → 401 (Req 2.5).
- Revocar sin token activo → 404 con ``error`` (Req 2.6).
- No existe endpoint que devuelva el token en claro tras la emisión: en la base
  sólo se guarda el hash (Req 2.2).
- Fallo de almacenamiento simulado con ``mock`` durante la emisión → 500 con
  ``error`` y token previo intacto (Req 2.7).

Los endpoints (``POST``/``DELETE`` ``/api/token``) están protegidos por
``api_login_required``; para simular una sesión iniciada se fija ``user_id`` en
la sesión de Flask con ``client.session_transaction()`` (igual que comprueba el
decorador).
"""

from __future__ import annotations

from unittest import mock

import auth
import database
from auth import _hash_token
from tests.strategies import insert_user


def _login(client, user_id: int) -> None:
    """Simula una sesión iniciada fijando ``user_id`` (como hace el decorador)."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _issue_token(client) -> str:
    """Emite un token vía ``POST /api/token`` y devuelve el valor en claro."""
    resp = client.post("/api/token")
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["token"]


# --------------------------------------------------------------------------- #
# Req 2.5: emisión / revocación sin sesión → 401
# --------------------------------------------------------------------------- #

def test_issue_without_session_returns_401(client):
    """POST /api/token sin sesión responde 401 con ``error`` (Req 2.5)."""
    resp = client.post("/api/token")

    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_revoke_without_session_returns_401(client):
    """DELETE /api/token sin sesión responde 401 con ``error`` (Req 2.5)."""
    resp = client.delete("/api/token")

    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_issue_without_session_does_not_create_token(client, connection):
    """Sin sesión no se genera ni almacena ningún token (Req 2.5)."""
    client.post("/api/token")

    n = connection.execute("SELECT COUNT(*) AS n FROM api_tokens").fetchone()["n"]
    assert n == 0


# --------------------------------------------------------------------------- #
# Req 2.6: revocar sin token activo → 404 con ``error``
# --------------------------------------------------------------------------- #

def test_revoke_without_active_token_returns_404(client, connection):
    """DELETE /api/token cuando el usuario no tiene token → 404 con ``error``."""
    user_id = insert_user(connection, "sin_token")
    _login(client, user_id)

    resp = client.delete("/api/token")

    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_revoke_after_issue_succeeds_then_404_second_time(client, connection):
    """Revocar un token activo responde 200; una segunda revocación → 404."""
    user_id = insert_user(connection, "revoca")
    _login(client, user_id)
    _issue_token(client)

    first = client.delete("/api/token")
    assert first.status_code == 200

    second = client.delete("/api/token")
    assert second.status_code == 404
    assert "error" in second.get_json()


# --------------------------------------------------------------------------- #
# Req 2.2: no hay forma de recuperar el token en claro; sólo se guarda el hash
# --------------------------------------------------------------------------- #

def test_plaintext_token_is_not_stored_only_hash(client, connection):
    """Tras emitir, la fila almacenada sólo contiene el hash, no el claro (Req 2.2)."""
    user_id = insert_user(connection, "solo_hash")
    _login(client, user_id)

    raw = _issue_token(client)

    row = connection.execute(
        "SELECT user_id, token_hash FROM api_tokens WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    assert row is not None
    stored = dict(row)
    # El hash guardado coincide con el hash determinista del claro...
    assert stored["token_hash"] == _hash_token(raw)
    # ...y no es el propio valor en claro.
    assert stored["token_hash"] != raw
    # Ninguna columna del registro contiene el valor en claro.
    assert raw not in tuple(str(v) for v in stored.values())


def test_no_endpoint_returns_plaintext_after_issue(client, connection):
    """No existe ruta que devuelva el claro tras la emisión (Req 2.2).

    Se verifica que ninguna regla de URL de la app expone un endpoint de
    lectura del token (GET) y que reintentar el POST no devuelve el mismo claro
    (rota a uno nuevo), de modo que el claro original no es recuperable.
    """
    user_id = insert_user(connection, "no_leak")
    _login(client, user_id)
    raw = _issue_token(client)

    # No hay ninguna regla que sirva GET sobre /api/token (sólo POST/DELETE).
    app = client.application
    rules = [r for r in app.url_map.iter_rules() if str(r.rule) == "/api/token"]
    assert rules, "Debe existir la ruta /api/token"
    for rule in rules:
        assert "GET" not in rule.methods

    # Reemitir devuelve un token distinto (rotación), nunca el claro anterior.
    raw_again = _issue_token(client)
    assert raw_again != raw


# --------------------------------------------------------------------------- #
# Req 2.7: fallo de almacenamiento simulado → 500 y token previo intacto
# --------------------------------------------------------------------------- #

def test_storage_failure_returns_500_and_keeps_previous_token(client, connection):
    """Si falla el almacenamiento durante la emisión → 500 y token previo intacto.

    Primero se emite un token válido (T1). Luego se parchea la conexión que usa
    ``generate_api_token`` para que ``execute`` lance, se solicita una nueva
    emisión y se espera 500 con ``error``. Finalmente se comprueba que el
    registro almacenado sigue siendo exactamente el de T1 (Req 2.7).
    """
    user_id = insert_user(connection, "fallo_storage")
    _login(client, user_id)

    raw_prev = _issue_token(client)
    hash_prev = _hash_token(raw_prev)

    stored_before = dict(
        connection.execute(
            "SELECT user_id, token_hash FROM api_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    )
    assert stored_before["token_hash"] == hash_prev

    # Conexión real para inspección posterior, pero cuyo execute falla dentro
    # de generate_api_token para simular el fallo de almacenamiento.
    real_conn = database.get_connection()

    class _FailingConn:
        def execute(self, *args, **kwargs):
            raise RuntimeError("fallo de almacenamiento simulado")

        def commit(self):  # pragma: no cover - no debería alcanzarse
            raise AssertionError("no debería llegar a commit")

        def rollback(self):
            real_conn.rollback()

        def close(self):
            real_conn.close()

    with mock.patch.object(auth, "get_connection", return_value=_FailingConn()):
        resp = client.post("/api/token")

    assert resp.status_code == 500
    assert "error" in resp.get_json()

    # El token previo sigue intacto: hay exactamente un token y es T1.
    rows = connection.execute(
        "SELECT token_hash FROM api_tokens WHERE user_id = ?", (user_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] == hash_prev
