"""
Seguridad central: hashing de contraseñas, JWT (acceso/refresh), TOTP 2FA.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Tuple

import bcrypt
import pyotp
from jose import JWTError, jwt

from app.config import settings

# ============================================================
# PASSWORD HASHING (bcrypt)
# ============================================================

# Límite máximo de bcrypt (72 bytes por bloque)
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """Genera hash seguro de la contraseña (bcrypt)."""
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise ValueError(f"La contraseña no puede exceder {BCRYPT_MAX_BYTES} caracteres (bcrypt).")
    salt = bcrypt.gensalt(rounds=settings.PASSWORD_HASH_ROUNDS)
    return bcrypt.hashpw(encoded, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica contraseña contra su hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def validate_password_policy(password: str) -> Tuple[bool, list]:
    """
    Valida la contraseña contra la política configurada.
    Retorna (es_válida, lista_de_errores).
    """
    errors = []

    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"Debe tener al menos {settings.PASSWORD_MIN_LENGTH} caracteres")

    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        errors.append(f"No puede exceder {BCRYPT_MAX_BYTES} caracteres")

    if settings.PASSWORD_REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
        errors.append("Debe contener al menos una letra mayúscula")

    if settings.PASSWORD_REQUIRE_LOWERCASE and not any(c.islower() for c in password):
        errors.append("Debe contener al menos una letra minúscula")

    if settings.PASSWORD_REQUIRE_DIGITS and not any(c.isdigit() for c in password):
        errors.append("Debe contener al menos un dígito")

    if settings.PASSWORD_REQUIRE_SPECIAL and not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        errors.append("Debe contener al menos un carácter especial")

    return (len(errors) == 0, errors)


# ============================================================
# JWT TOKENS
# ============================================================


def create_access_token(
    user_id: uuid.UUID,
    username: str,
    empleado_id: uuid.UUID | None = None,
    expires_minutes: int | None = None,
) -> str:
    """
    Crea un JWT de acceso (corto plazo).
    Payload incluye: sub (user_id), username, empleado_id, iat, exp, iss, aud.
    """
    if expires_minutes is None:
        expires_minutes = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES

    now = datetime.now(UTC)
    expire = now + timedelta(minutes=expires_minutes)

    payload = {
        "sub": str(user_id),
        "username": username,
        "empleado_id": str(empleado_id) if empleado_id else None,
        "type": "access",
        "iat": now,
        "exp": expire,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    private_key = _load_private_key()
    return jwt.encode(payload, private_key, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    expires_days: int | None = None,
) -> str:
    """
    Crea un JWT de refresh (largo plazo).
    El session_id permite revocar tokens individuales.
    """
    if expires_days is None:
        expires_days = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS

    now = datetime.now(UTC)
    expire = now + timedelta(days=expires_days)

    payload = {
        "sub": str(user_id),
        "session_id": str(session_id),
        "type": "refresh",
        "iat": now,
        "exp": expire,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    private_key = _load_private_key()
    return jwt.encode(payload, private_key, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, token_type: str = "access") -> dict:
    """
    Decodifica y valida un JWT.
    Retorna el payload o lanza JWTError.
    """
    public_key = _load_public_key()
    payload = jwt.decode(
        token,
        public_key,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )

    if payload.get("type") != token_type:
        raise JWTError(f"Tipo de token incorrecto: esperado '{token_type}'")

    return payload


def decode_access_token(token: str) -> dict:
    """Decodifica token de acceso. Lanza JWTError si inválido/expirado."""
    return decode_token(token, "access")


def decode_refresh_token(token: str) -> dict:
    """Decodifica token refresh. Lanza JWTError si inválido/expirado."""
    return decode_token(token, "refresh")


def get_token_user_id(token: str) -> uuid.UUID | None:
    """Extrae user_id de un token de acceso (sin validar expiración completa)."""
    try:
        payload = decode_access_token(token)
        return uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None


# ============================================================
# 2FA (TOTP)
# ============================================================


def generate_totp_secret() -> str:
    """Genera secreto TOTP nuevo (Base32)."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str) -> str:
    """Genera URI otpauth:// para QR code."""
    totp = pyotp.TOTP(secret, digits=settings.TOTP_DIGITS, interval=settings.TOTP_INTERVAL)
    return totp.provisioning_uri(name=username, issuer_name=settings.TOTP_ISSUER_NAME)


def verify_totp(secret: str, code: str) -> bool:
    """Verifica código TOTP. Acepta ±1 ventana de tiempo para tolerancia de reloj."""
    try:
        totp = pyotp.TOTP(secret, digits=settings.TOTP_DIGITS, interval=settings.TOTP_INTERVAL)
        return totp.verify(code, valid_window=1)
    except Exception:
        return False


# ============================================================
# CARGA DE LLAVES JWT
# ============================================================

_private_key_cache: str | None = None
_public_key_cache: str | None = None


def _load_private_key() -> str:
    """Carga llave privada RS256 desde archivo (cacheada)."""
    global _private_key_cache
    if _private_key_cache is None:
        try:
            with open(settings.JWT_PRIVATE_KEY_PATH) as f:
                _private_key_cache = f.read()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Llave privada JWT no encontrada: {settings.JWT_PRIVATE_KEY_PATH}. "
                f"Generar con: openssl genrsa -out {settings.JWT_PRIVATE_KEY_PATH} 2048"
            ) from exc
    return _private_key_cache


def _load_public_key() -> str:
    """Carga llave pública RS256 desde archivo (cacheada)."""
    global _public_key_cache
    if _public_key_cache is None:
        try:
            with open(settings.JWT_PUBLIC_KEY_PATH) as f:
                _public_key_cache = f.read()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Llave pública JWT no encontrada: {settings.JWT_PUBLIC_KEY_PATH}. "
                f"Generar con: openssl rsa -in {settings.JWT_PRIVATE_KEY_PATH} "
                f"-pubout -out {settings.JWT_PUBLIC_KEY_PATH}"
            ) from exc
    return _public_key_cache


# ============================================================
# UTILIDADES DE SESIÓN
# ============================================================


def generate_session_token_hash(token: str) -> str:
    """Genera hash del refresh token para almacenar en BD (no guardar el token)."""
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


def is_token_expired(payload: dict) -> bool:
    """Verifica si un token está expirado según su campo exp."""
    exp = payload.get("exp")
    if exp is None:
        return True
    return datetime.fromtimestamp(exp, tz=UTC) < datetime.now(UTC)
