"""Property 3: Rechazo de credenciales inválidas (feature: external-data-api).

# Feature: external-data-api, Property 3: Rechazo de credenciales inválidas

Valida que, para toda entrada de autenticación inválida (encabezado ausente,
esquema distinto de ``Bearer``, ``Bearer`` con token vacío o sólo espacios, o un
token que no corresponde a ningún registro almacenado), la resolución no
identifica a ningún usuario y el endpoint protegido responde 401 con un cuerpo
JSON que incluye ``error``.

**Validates: Requirements 1.2, 1.3, 1.6**

La prueba prioriza la aserción HTTP (401) porque la propiedad trata sobre el
rechazo a nivel de endpoint; adicionalmente verifica que ``resolve_token_user``
devuelve ``None`` para las mismas entradas.
"""

from __future__ import annotations

import secrets

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from auth import resolve_token_user, token_required, generate_api_token
from tests.strategies import insert_user


# ---------- Estrategias de encabezados de autorización inválidos ----------

# Texto de token arbitrario (no vacío tras strip) usado para esquemas no Bearer
# y para tokens inexistentes.
_token_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=0x2FFF, blacklist_categories=("Cs",)),
    min_size=1,
    max_size=60,
).filter(lambda s: len(s.strip()) > 0)

# Cadenas compuestas sólo por espacios en blanco (para el caso "Bearer vacío").
# Se restringe a espacio/tab: son en blanco (``str.strip`` los elimina, así que
# el token queda vacío y debe rechazarse) pero, a diferencia de ``\r``/``\n``,
# son válidos como valor de encabezado HTTP y permiten ejercitar el caso a nivel
# HTTP además del nivel de función pura.
_whitespace = st.text(alphabet=" \t", min_size=0, max_size=6)

# Esquemas distintos de "Bearer " (incluyendo variaciones de mayúsculas, que el
# diseño rechaza por comparar con el prefijo exacto "Bearer ").
_other_schemes = st.sampled_from(
    ["Basic", "Token", "bearer", "BEARER", "Bearer2", "ApiKey", "Digest", "OAuth"]
)


@st.composite
def invalid_auth_headers(draw):
    """Genera un encabezado ``Authorization`` inválido de una de estas clases:

    - ``None``: encabezado ausente (Req 1.2).
    - Esquema distinto de ``Bearer <token>`` (Req 1.6).
    - ``Bearer`` con token vacío o sólo espacios (Req 1.6).
    - Cadena arbitraria sin esquema reconocido (Req 1.6).

    Nota: el caso de "token inexistente" (Req 1.3) se cubre por separado en la
    prueba, porque requiere un valor con el prefijo ``Bearer `` correcto pero que
    no coincide con ningún registro almacenado.
    """
    kind = draw(st.integers(min_value=0, max_value=3))
    if kind == 0:
        return None
    if kind == 1:
        # Esquema distinto: "Basic <algo>", "Token <algo>", "bearer <algo>", ...
        scheme = draw(_other_schemes)
        rest = draw(_token_text)
        return f"{scheme} {rest}"
    if kind == 2:
        # "Bearer" seguido de vacío o sólo espacios.
        return "Bearer " + draw(_whitespace)
    # Cadena arbitraria que no empieza por "Bearer ".
    raw = draw(_token_text)
    return raw if not raw.startswith("Bearer ") else "X" + raw


def _register_protected_route(flask_app):
    """Registra (una sola vez) una ruta de prueba protegida con ``token_required``.

    Devuelve la URL de la ruta. La vista sólo responde 200 si el token es válido;
    el decorador es quien produce el 401 para credenciales inválidas.
    """
    rule = "/__test__/protected_prop3"
    if rule not in {r.rule for r in flask_app.url_map.iter_rules()}:

        @token_required
        def _protected_view():
            from flask import g, jsonify

            return jsonify({"ok": True, "user_id": g.api_user["id"]}), 200

        flask_app.add_url_rule(rule, "prop3_protected_view", _protected_view)
    return rule


# ---------- Property 3 ----------

@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(header=invalid_auth_headers())
def test_reject_malformed_or_missing_credentials(app, header):
    """Encabezados ausentes / mal formados / ``Bearer`` vacío → None y 401."""
    # Nivel de función pura: no debe identificar a ningún usuario.
    assert resolve_token_user(header) is None

    # Nivel HTTP: el endpoint protegido responde 401 con cuerpo JSON {"error": ...}.
    rule = _register_protected_route(app)
    client = app.test_client()
    headers = {} if header is None else {"Authorization": header}
    resp = client.get(rule, headers=headers)

    assert resp.status_code == 401
    assert resp.is_json
    body = resp.get_json()
    assert isinstance(body, dict) and "error" in body


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_reject_nonexistent_token(app, temp_db, data):
    """``Bearer <token>`` con un token que no está almacenado → None y 401 (Req 1.3).

    Se emite un token real para un usuario (para que exista al menos un registro)
    y luego se presenta un token aleatorio distinto que no coincide con ninguno.
    """
    from database import get_connection

    conn = get_connection()
    user_id = insert_user(conn, "prop3")
    conn.close()

    stored_raw = generate_api_token(user_id)

    # Genera un token con el formato correcto pero que no está almacenado.
    bogus = data.draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
            min_size=1,
            max_size=80,
        ).filter(lambda t: t.strip() and t != stored_raw)
    )
    # Refuerzo por si acaso la generación aleatoria coincidiera (probabilidad ~0).
    if bogus == stored_raw:
        bogus = stored_raw + secrets.token_urlsafe(4)

    header = f"Bearer {bogus}"

    assert resolve_token_user(header) is None

    rule = _register_protected_route(app)
    client = app.test_client()
    resp = client.get(rule, headers={"Authorization": header})

    assert resp.status_code == 401
    assert resp.is_json
    body = resp.get_json()
    assert isinstance(body, dict) and "error" in body
