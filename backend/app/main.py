"""
Aplicación FastAPI - Sistema de Gestión de Cilindros de Gas AGAS.

Ejecución local:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import AppException
from app.database import check_database_connection, close_db

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("agas")


# ============================================================
# LIFECYCLE
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque y apagado de la aplicación."""
    logger.info(
        "Iniciando %s v%s (entorno: %s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
    )

    db_ok = await check_database_connection()
    if db_ok:
        logger.info("Conexión a base de datos: OK")
    else:
        logger.warning("La base de datos NO está disponible. Los endpoints que la requieren fallarán.")

    yield

    logger.info("Apagando aplicación y liberando conexiones...")
    await close_db()


# ============================================================
# APP FACTORY
# ============================================================


def create_app() -> FastAPI:
    """Crea y configura la instancia de FastAPI."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=("API del Sistema Web de Gestión, Valorización y Trazabilidad de Cilindros de Gas para AGAS."),
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )

    # --- Rutas ---
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # --- Handlers de error ---
    _register_exception_handlers(app)

    # --- Raíz ---
    @app.get("/", include_in_schema=False)
    async def root() -> Dict[str, Any]:
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "api": settings.API_V1_PREFIX,
            "docs": "/docs" if settings.DEBUG else "deshabilitado en producción",
        }

    return app


# ============================================================
# HANDLERS DE EXCEPCIÓN
# ============================================================


def _register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers con formato de respuesta consistente:
    {"detail": {"code": ..., "message": ..., "extra": {...}}}
    """

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        logger.log(
            level,
            "AppException %s [%s] %s %s",
            exc.status_code,
            exc.code,
            request.method,
            request.url.path,
            extra={"exc_message": exc.message},
        )
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            field_errors.append(
                {
                    "field": loc,
                    "message": err.get("msg", "Valor inválido"),
                    "type": err.get("type", ""),
                }
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": {
                    "code": "VALIDATION_ERROR",
                    "message": "Datos de entrada inválidos",
                    "extra": {"field_errors": field_errors},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {
            400: "Solicitud inválida",
            401: "No autenticado",
            403: "Acceso denegado",
            404: "Recurso no encontrado",
            405: "Método no permitido",
            409: "Conflicto con el estado actual del recurso",
            422: "Datos de entrada inválidos",
            429: "Demasiadas solicitudes. Intente más tarde.",
            500: "Error interno del servidor",
            503: "Servicio no disponible",
        }
        code = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            500: "INTERNAL_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }.get(exc.status_code, "HTTP_ERROR")

        detail = exc.detail if isinstance(exc.detail, str) else messages.get(exc.status_code, "Error")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"code": code, "message": detail}},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Error inesperado %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": {
                    "code": "INTERNAL_ERROR",
                    "message": "Error interno del servidor. Contacte al administrador.",
                }
            },
        )


# ============================================================
# INSTANCIA GLOBAL
# ============================================================

app = create_app()
