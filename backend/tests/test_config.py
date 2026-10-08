"""
Tests de configuración de la aplicación (ETAPA 1).
"""

from __future__ import annotations

from app.config import Settings, settings


def test_valores_basicos_de_la_aplicacion() -> None:
    assert settings.APP_NAME == "AGAS Cilindros API"
    assert settings.APP_VERSION == "1.0.0"
    assert settings.API_V1_PREFIX == "/api/v1"


def test_prefijo_de_apis_v1_con_formato() -> None:
    assert settings.API_V1_PREFIX.startswith("/")
    assert not settings.API_V1_PREFIX.endswith("/")


def test_url_de_base_de_datos_async() -> None:
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert f":{settings.DATABASE_PORT}/" in settings.DATABASE_URL
    assert settings.DATABASE_URL.endswith(f"/{settings.DATABASE_NAME}")


def test_url_de_base_de_datos_sync() -> None:
    assert settings.DATABASE_URL_SYNC.startswith("postgresql://")
    assert settings.DATABASE_URL_SYNC.endswith(f"/{settings.DATABASE_NAME}")


def test_url_de_redis() -> None:
    assert settings.REDIS_CONNECTION_URL.startswith("redis://")
    assert str(settings.REDIS_PORT) in settings.REDIS_CONNECTION_URL


def test_url_de_minio_para_api_s3() -> None:
    # S3 genérico (SeaweedFS en Docker, D20); el host y puerto no llevan esquema.
    assert settings.MINIO_ENDPOINT
    assert ":" in settings.MINIO_ENDPOINT
    assert not settings.MINIO_ENDPOINT.startswith("http")


def test_llaves_jwt_tienen_valores() -> None:
    assert settings.JWT_ALGORITHM == "RS256"
    assert settings.JWT_PRIVATE_KEY_PATH.endswith(".pem")
    assert settings.JWT_PUBLIC_KEY_PATH.endswith(".pem")
    assert settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES <= 60
    assert settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS >= 1


def test_password_exige_minimo_10_caracteres() -> None:
    assert settings.PASSWORD_MIN_LENGTH >= 10
    assert settings.PASSWORD_REQUIRE_UPPERCASE
    assert settings.PASSWORD_REQUIRE_LOWERCASE
    assert settings.PASSWORD_REQUIRE_DIGITS
    assert settings.PASSWORD_REQUIRE_SPECIAL


def test_settings_permite_sobreescribir_con_valores_de_entorno(monkeypatch) -> None:
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "50")

    fresh = Settings()

    assert fresh.APP_VERSION == "9.9.9"
    assert fresh.DEFAULT_PAGE_SIZE == 50
