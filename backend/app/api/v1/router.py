"""
Enrutador principal de la API v1.

Agrega los routers de cada módulo. Los módulos se habilitan a medida que
se implementan (ver documento de análisis, sección 15.3 y etapas 0-12).

Uso de cada módulo:
    from app.api.v1.endpoints.<modulo> import router as <modulo>_router
    api_router.include_router(<modulo>_router, prefix="/<prefijo>", tags=["<Modulo>"])
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.health import router as health_router

api_router = APIRouter()

# ============================================================
# SIEMPRE ACTIVOS (sistema)
# ============================================================
api_router.include_router(health_router)

# ============================================================
# MÓDULOS (se habilitan por etapa)
# ============================================================
# Etapa 2 - Autenticación y seguridad:
#   auth (login/refresh/me) — el resto se habilita por subetapas:
#   usuarios, empleados, tareas, permisos, sesiones, audit_log
api_router.include_router(auth_router, prefix="/auth")

# Etapa 3 - Maestros:
#   clientes, propietarios, categorias, parametros

# Etapa 4 - Inventario de cilindros:
#   cilindros, ubicaciones, movimientos

# Etapa 5 - Operaciones:
#   recepciones, inspecciones, ordenes_llenado, ordenes_reparacion, control_calidad

# Etapa 6 - Comercial:
#   productos, servicios, precios, presupuestos

# Etapa 7 - Despacho y entregas:
#   entregas, devoluciones, choferes, vehiculos, documentos_despacho

# Etapa 8 - Documentos y valorización:
#   documentos, pagos, valorizaciones

# Etapa 9 - Reportes:
#   reportes, dashboard

# Etapa 10 - Integraciones:
#   webhooks, integraciones

# Etapa 11 - Notificaciones:
#   notificaciones
