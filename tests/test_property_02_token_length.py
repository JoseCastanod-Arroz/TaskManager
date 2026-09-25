"""Prueba de propiedad (feature: external-data-api).

# Feature: external-data-api, Property 2: Longitud del token emitido
Para todo usuario, el Token_API en claro devuelto por la emisión tiene una
longitud de entre 32 y 128 caracteres, ambos inclusive.

Valida: Requisitos 2.1
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from auth import generate_api_token
from tests.strategies import insert_user, usernames

# Rango válido de longitud del token en claro (inclusive), según el diseño.
MIN_TOKEN_LEN = 32
MAX_TOKEN_LEN = 128


# Feature: external-data-api, Property 2: Longitud del token emitido
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(username=usernames)
def test_issued_token_length_within_range(connection, username):
    """El token en claro emitido mide entre 32 y 128 caracteres (inclusive)."""
    user_id = insert_user(connection, username=username)

    raw_token = generate_api_token(user_id)

    assert isinstance(raw_token, str)
    assert MIN_TOKEN_LEN <= len(raw_token) <= MAX_TOKEN_LEN, (
        f"Longitud del token fuera de rango: {len(raw_token)} "
        f"(esperado {MIN_TOKEN_LEN}..{MAX_TOKEN_LEN})"
    )
