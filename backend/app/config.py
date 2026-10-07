"""
Configuración de la aplicación usando Pydantic Settings.
Carga variables de entorno desde .env y valida tipos.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ============================================================
    # APP GENERAL
    # ============================================================
    APP_NAME: str = "AGAS Cilindros API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development, staging, production
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = Field(..., min_length=32)
    ALLOWED_HOSTS: List[str] = ["*"]

    # ============================================================
    # DATABASE (PostgreSQL)
    # ============================================================
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_USER: str = "agas_user"
    DATABASE_PASSWORD: str = Field(..., min_length=8)
    DATABASE_NAME: str = "agas_cilindros"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_ECHO: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (
            f"postgresql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    # ============================================================
    # REDIS
    # ============================================================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0
    REDIS_URL: str | None = None

    @property
    def REDIS_CONNECTION_URL(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ============================================================
    # MINIO (S3-compatible Object Storage)
    # ============================================================
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = Field(..., min_length=3)
    MINIO_SECRET_KEY: str = Field(..., min_length=8)
    MINIO_SECURE: bool = False
    MINIO_BUCKET_FILES: str = "agas-files"
    MINIO_BUCKET_BACKUPS: str = "agas-backups"
    MINIO_PRESIGNED_URL_EXPIRY: int = 3600  # 1 hour

    # ============================================================
    # JWT AUTHENTICATION
    # ============================================================
    JWT_ALGORITHM: str = "RS256"
    JWT_PRIVATE_KEY_PATH: str = "/app/secrets/jwt_private.pem"
    JWT_PUBLIC_KEY_PATH: str = "/app/secrets/jwt_public.pem"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ISSUER: str = "agas-cilindros"
    JWT_AUDIENCE: str = "agas-cilindros-api"

    # ============================================================
    # 2FA (TOTP)
    # ============================================================
    TOTP_ISSUER_NAME: str = "AGAS Cilindros"
    TOTP_DIGITS: int = 6
    TOTP_INTERVAL: int = 30

    # ============================================================
    # PASSWORD POLICY
    # ============================================================
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGITS: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True
    PASSWORD_HASH_ROUNDS: int = 12
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = 30

    # ============================================================
    # CORS
    # ============================================================
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    # ============================================================
    # RATE LIMITING
    # ============================================================
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 100
    RATE_LIMIT_BURST: int = 20

    # ============================================================
    # FILE UPLOAD
    # ============================================================
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_FILE_TYPES: List[str] = [
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
    ]

    # ============================================================
    # EMAIL (para recuperación contraseña, notificaciones futuras)
    # ============================================================
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_TLS: bool = True
    EMAIL_FROM: str = "noreply@agas.cl"
    EMAIL_FROM_NAME: str = "AGAS Cilindros"

    # ============================================================
    # PDF SERVICE (Puppeteer microservice)
    # ============================================================
    PDF_SERVICE_URL: str = "http://pdf-service:3001"
    PDF_SERVICE_TIMEOUT: int = 60

    # ============================================================
    # CELERY
    # ============================================================
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 300

    # ============================================================
    # PAGINATION DEFAULTS
    # ============================================================
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # ============================================================
    # BUSINESS RULES DEFAULTS (sobrescribibles por tabla parametro)
    # ============================================================
    DEFAULT_IVA_PERCENTAGE: float = 19.0
    DEFAULT_CURRENCY: str = "CLP"
    ROUNDING_DECIMALS: int = 0
    DOCUMENT_TOLERANCE: int = 10
    PROPIETARIO_AGAS_RUT: str = "76.000.000-0"
    DAYS_ALERT_HYDRAULIC_TEST: int = 30

    # ============================================================
    # LOGGING
    # ============================================================
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json or console
    LOG_FILE_PATH: str | None = None

    # ============================================================
    # MONITORING
    # ============================================================
    ENABLE_PROMETHEUS_METRICS: bool = True
    METRICS_PORT: int = 9090


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
