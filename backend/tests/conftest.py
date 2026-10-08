"""
Fixtures y configuración global del entorno de pruebas.

Importante: las variables de entorno se configuran ANTES de importar módulos
de la aplicación, porque `app.config.settings` se instancia en el import
y exige valores como SECRET_KEY, DATABASE_PASSWORD y las llaves de MinIO.

Convención: los tests de BD usan la base `agas_cilindros_test` (aislada de la
base de desarrollo). Si la BD de prueba no está disponible, esos tests se
omiten (skip) en lugar de fallar; en CI se fija `TESTS_REQUIRE_DB=1` para que
la indisponibilidad sea un fallo explícito y nunca un "falso verde".
"""

from __future__ import annotations

import os
import pathlib

# --- Configuración de entorno para tests (ANTES de importar la app) ---
#
# `app.config.settings` se instancia en el import y exige SECRET_KEY,
# DATABASE_PASSWORD y las llaves de MinIO. Si existe backend/.env (dev local),
# se dejan esos valores reales para que pydantic los lea; si no existe (CI o
# clone limpio), se inyectan defaults válidos de prueba.
_env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"

if not _env_file.is_file():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 24)  # >= 32 chars
    os.environ.setdefault("DATABASE_PASSWORD", "testpassword123")
    os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
    os.environ.setdefault("MINIO_SECRET_KEY", "test-secret-key-123")

# La BD de pruebas siempre se aísla de la de desarrollo.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_NAME", "agas_cilindros_test")

import pytest  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def jwt_keypair(tmp_path_factory):
    """
    Genera un par de llaves RS256 de prueba y apunta la configuración a ellas.

    Las llaves se cargan de forma perezosa (cache) en app.core.security, así
    que además se limpian ambas cachés antes y después de la sesión de tests.
    """
    from app.config import settings
    from app.core import security as security_module

    keys_dir = tmp_path_factory.mktemp("jwt")
    private_path = keys_dir / "jwt_private.pem"
    public_path = keys_dir / "jwt_public.pem"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    saved = (settings.JWT_PRIVATE_KEY_PATH, settings.JWT_PUBLIC_KEY_PATH)
    settings.JWT_PRIVATE_KEY_PATH = str(private_path)
    settings.JWT_PUBLIC_KEY_PATH = str(public_path)
    security_module._private_key_cache = None
    security_module._public_key_cache = None

    yield private_path, public_path

    settings.JWT_PRIVATE_KEY_PATH, settings.JWT_PUBLIC_KEY_PATH = saved
    security_module._private_key_cache = None
    security_module._public_key_cache = None
