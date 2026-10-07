"""
Endpoints de salud y estado del sistema.
GET /health        → estado general (liveness)
GET /health/detail → estado detallado (BD, versión)
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import check_database_connection, get_database_version

router = APIRouter(tags=["Sistema"])


@router.get(
    "/health",
    summary="Health check general",
    description="Endpoint de liveness para balanceadores y orquestadores.",
)
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@router.get(
    "/health/detail",
    summary="Health check detallado",
    description="Estado de la base de datos y versión del motor.",
)
async def health_detail() -> JSONResponse:
    db_ok = await check_database_connection()
    db_version = await get_database_version() if db_ok else None

    payload = {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": {
            "connected": db_ok,
            "version": db_version,
        },
    }
    return JSONResponse(
        content=payload,
        status_code=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
