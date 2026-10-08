"""
Tests de seguridad (ETAPA 1): hashing bcrypt, política de contraseñas,
JWT RS256 (acceso/refresh) y TOTP 2FA.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import JWTError

from app.config import settings
from app.core.security import (
    BCRYPT_MAX_BYTES,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    generate_totp_secret,
    get_token_user_id,
    get_totp_uri,
    hash_password,
    is_token_expired,
    validate_password_policy,
    verify_password,
    verify_totp,
)

# ============================================================
# HASHING BCRYPT
# ============================================================


def test_hash_y_verifica_password() -> None:
    hashed = hash_password("Passw0rd!123")

    assert hashed.startswith("$2b$")
    assert verify_password("Passw0rd!123", hashed)


def test_hash_rechaza_password_incorrecta() -> None:
    hashed = hash_password("Passw0rd!123")

    assert not verify_password("otra-clave-123", hashed)
    assert not verify_password("", hashed)


def test_hash_usa_sal_aleatoria() -> None:
    h1 = hash_password("Passw0rd!123")
    h2 = hash_password("Passw0rd!123")

    assert h1 != h2


def test_hash_rechaza_password_sobre_72_bytes() -> None:
    with pytest.raises(ValueError, match="72"):
        hash_password("A" * (BCRYPT_MAX_BYTES + 1))


def test_verify_con_hash_invalido_no_lanza_excepcion() -> None:
    assert not verify_password("cualquiera", "no-es-un-hash")


# ============================================================
# POLÍTICA DE CONTRASEÑAS
# ============================================================


def test_politica_acepta_password_valida() -> None:
    ok, errors = validate_password_policy("ClaveSegura2026!")

    assert ok
    assert errors == []


def test_politica_exige_longitud_minima() -> None:
    ok, errors = validate_password_policy("Aa1!")

    assert not ok
    assert any("caracteres" in e for e in errors)


def test_politica_exige_mayuscula() -> None:
    ok, errors = validate_password_policy("todominuscula2026!")

    assert not ok
    assert any("mayúscula" in e for e in errors)


def test_politica_exige_minuscula() -> None:
    ok, errors = validate_password_policy("TODOMAYUSCULA2026!")

    assert not ok
    assert any("minúscula" in e for e in errors)


def test_politica_exige_digito() -> None:
    ok, errors = validate_password_policy("SinNumerosEsto!")

    assert not ok
    assert any("dígito" in e for e in errors)


def test_politica_exige_caracter_especial() -> None:
    ok, errors = validate_password_policy("SinEspecial2026")

    assert not ok
    assert any("especial" in e for e in errors)


# ============================================================
# JWT RS256
# ============================================================


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    empleado_id = uuid.uuid4()

    token = create_access_token(user_id=user_id, username="admin", empleado_id=empleado_id)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["username"] == "admin"
    assert payload["empleado_id"] == str(empleado_id)
    assert payload["type"] == "access"
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE


def test_refresh_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    token = create_refresh_token(user_id=user_id, session_id=session_id)
    payload = decode_refresh_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["session_id"] == str(session_id)
    assert payload["type"] == "refresh"


def test_tipo_de_token_no_coincide() -> None:
    refresh = create_refresh_token(user_id=uuid.uuid4(), session_id=uuid.uuid4())

    with pytest.raises(JWTError, match="Tipo de token"):
        decode_access_token(refresh)


def test_token_manipulado_es_rechazado() -> None:
    token = create_access_token(user_id=uuid.uuid4(), username="admin")
    header, body, signature = token.split(".")
    # Altera un carácter intermedio de la firma (el último solo cubre bits de
    # relleno base64 y no cambiaría los bytes decodificados).
    mid = len(signature) // 2
    tampered = signature[:mid] + ("A" if signature[mid] != "A" else "B") + signature[mid + 1 :]

    with pytest.raises(JWTError):
        decode_access_token(f"{header}.{body}.{tampered}")


def test_token_expirado_es_rechazado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    token = create_access_token(user_id=uuid.uuid4(), username="admin")

    with pytest.raises(JWTError):
        decode_access_token(token)


def test_get_token_user_id_extrae_identidad() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, username="admin")

    assert get_token_user_id(token) == user_id


def test_get_token_user_id_con_token_invalido() -> None:
    assert get_token_user_id("esto-no-es-un-jwt") is None


# ============================================================
# TOTP 2FA
# ============================================================


def test_genera_secreto_totp_base32() -> None:
    secret = generate_totp_secret()

    assert len(secret) >= 16
    assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def test_uri_totp_tiene_formato_otpauth() -> None:
    import pyotp

    secret = generate_totp_secret()
    uri = get_totp_uri(secret, "admin")

    assert uri.startswith("otpauth://totp/")
    assert "AGAS" in uri
    assert "admin" in uri
    assert pyotp.TOTP(secret).provisioning_uri(name="admin", issuer_name=settings.TOTP_ISSUER_NAME) == uri


def test_verify_totp_acepta_codigo_valido() -> None:
    import pyotp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret, digits=settings.TOTP_DIGITS, interval=settings.TOTP_INTERVAL).now()

    assert verify_totp(secret, code)


def test_verify_totp_rechaza_codigo_invalido() -> None:
    secret = generate_totp_secret()

    assert not verify_totp(secret, "000000")
    assert not verify_totp(secret, "abcdef")


# ============================================================
# UTILIDADES DE TOKEN
# ============================================================


def test_is_token_expired_detecta_expiracion() -> None:
    pasado = {"exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())}
    futuro = {"exp": int((datetime.now(UTC) + timedelta(minutes=60)).timestamp())}

    assert is_token_expired(pasado) is True
    assert is_token_expired(futuro) is False
    assert is_token_expired({}) is True
