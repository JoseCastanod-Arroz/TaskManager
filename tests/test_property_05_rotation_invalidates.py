"""Prueba de propiedad 5 (feature: external-data-api).

La rotación invalida el token anterior: para todo usuario que ya posee un
``Token_API`` T1, tras emitir un nuevo token T2 el usuario tiene exactamente un
token activo. Presentar T2 identifica al usuario; presentar T1 es rechazado
(la resolución retorna ``None``). Además, sólo queda una fila de ``api_tokens``
para ese usuario.

Archivo dedicado para evitar colisiones con otras tareas PBT concurrentes.
"""

from hypothesis import HealthCheck, given, settings

from auth import generate_api_token, resolve_token_user
from tests.strategies import insert_user, usernames


# Feature: external-data-api, Property 5: La rotación invalida el token anterior
# Valida: Requisitos 2.3, 2.8
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=usernames)
def test_rotation_invalidates_previous_token(connection, username):
    # Crear un usuario (nombre único garantizado por insert_user).
    user_id = insert_user(connection, username=username)

    # Emitir el primer token (T1 = raw1) y luego rotar a un nuevo token (T2 = raw2).
    raw1 = generate_api_token(user_id)
    raw2 = generate_api_token(user_id)

    # Los dos tokens en claro deben ser distintos (la rotación produce uno nuevo).
    assert raw1 != raw2

    # Presentar T2 identifica exactamente a ese usuario.
    resolved_new = resolve_token_user("Bearer " + raw2)
    assert resolved_new is not None
    assert resolved_new["id"] == user_id

    # Presentar T1 (el anterior) ya no identifica a nadie: la rotación lo invalidó.
    resolved_old = resolve_token_user("Bearer " + raw1)
    assert resolved_old is None

    # Existe exactamente una fila de token activa para el usuario.
    count = connection.execute(
        "SELECT COUNT(*) AS n FROM api_tokens WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]
    assert count == 1
