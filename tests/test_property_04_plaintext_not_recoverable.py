"""Prueba de propiedad 4 (feature: external-data-api).

Property 4: El valor en claro del token no es recuperable del registro.
Valida: Requisitos 1.4.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from auth import _hash_token, generate_api_token
from tests.strategies import insert_user


# Feature: external-data-api, Property 4: El valor en claro del token no es recuperable del registro
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
    min_size=3,
    max_size=20,
))
def test_plaintext_token_not_recoverable_from_record(connection, username):
    """Para todo Token_API emitido, el registro almacenado no contiene el valor
    en claro en ninguna columna y su ``token_hash`` es igual al hash
    determinista del claro (y distinto del claro)."""
    user_id = insert_user(connection, username=username)

    raw = generate_api_token(user_id)

    row = connection.execute(
        "SELECT * FROM api_tokens WHERE user_id = ?", (user_id,)
    ).fetchone()
    assert row is not None, "debería existir un registro de token para el usuario"

    # Ninguna columna del registro contiene el valor en claro.
    for key in row.keys():
        value = row[key]
        if isinstance(value, str):
            assert raw not in value, (
                f"la columna '{key}' contiene el valor en claro del token"
            )
        else:
            assert value != raw

    # El hash almacenado es el hash determinista del claro y no el claro mismo.
    assert row["token_hash"] == _hash_token(raw)
    assert row["token_hash"] != raw
