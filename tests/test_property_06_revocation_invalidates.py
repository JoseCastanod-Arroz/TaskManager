"""Prueba de propiedad 6 (feature: external-data-api).

La revocación invalida el token: para todo usuario con un ``Token_API`` activo
T, tras revocarlo con ``revoke_api_token(user_id)`` (que devuelve ``True``), la
presentación de T mediante ``resolve_token_user("Bearer " + raw)`` es rechazada
(la resolución retorna ``None``) y no queda ninguna fila de ``api_tokens`` para
ese usuario.

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.
"""

from hypothesis import HealthCheck, given, settings

from auth import generate_api_token, resolve_token_user, revoke_api_token
from tests.strategies import insert_user, usernames


# Feature: external-data-api, Property 6: La revocación invalida el token
# Valida: Requisitos 2.4
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=usernames)
def test_revocation_invalidates_token(connection, username):
    # Crear un usuario (nombre único garantizado por insert_user).
    user_id = insert_user(connection, username=username)

    # Emitir un token (T = raw) y confirmar que resuelve al usuario propietario.
    raw = generate_api_token(user_id)
    resolved_before = resolve_token_user("Bearer " + raw)
    assert resolved_before is not None
    assert resolved_before["id"] == user_id

    # Revocar el token activo del usuario: debe devolver True (había un token).
    assert revoke_api_token(user_id) is True

    # Tras la revocación, presentar T ya no identifica a nadie.
    resolved_after = resolve_token_user("Bearer " + raw)
    assert resolved_after is None

    # No queda ninguna fila de token para ese usuario.
    count = connection.execute(
        "SELECT COUNT(*) AS n FROM api_tokens WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]
    assert count == 0
