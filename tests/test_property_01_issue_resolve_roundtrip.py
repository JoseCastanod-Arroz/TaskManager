"""Prueba de propiedad 1 (feature: external-data-api).

Round-trip de emisión y aceptación del token: para todo usuario, si se emite un
``Token_API`` con ``generate_api_token`` y se presenta como
``Authorization: Bearer <token_en_claro>``, la resolución identifica exactamente
a ese usuario como ``Usuario_Propietario`` (con su ``id`` y ``username``).

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from auth import generate_api_token, resolve_token_user
from tests.strategies import insert_user, usernames


# Feature: external-data-api, Property 1: Round-trip de emisión y aceptación del token
# Valida: Requisitos 1.1, 1.5, 2.1, 2.8
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=usernames)
def test_issue_resolve_roundtrip(connection, username):
    # Crear un usuario (nombre único garantizado por insert_user).
    user_id = insert_user(connection, username=username)

    # Emitir el Token_API para ese usuario.
    raw = generate_api_token(user_id)

    # Presentar el token en claro bajo el esquema Bearer y resolver.
    resolved = resolve_token_user("Bearer " + raw)

    # La resolución identifica exactamente a ese usuario (id + username).
    assert resolved is not None
    assert resolved["id"] == user_id

    row = connection.execute(
        "SELECT username FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    assert resolved["username"] == row["username"]
