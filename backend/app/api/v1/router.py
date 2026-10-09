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

from app.api.v1.endpoints.areas import router as areas_router
from app.api.v1.endpoints.auditoria import router as auditoria_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.categorias import router as categorias_router
from app.api.v1.endpoints.cilindros import router as cilindros_router
from app.api.v1.endpoints.clientes import router as clientes_router
from app.api.v1.endpoints.empleados import router as empleados_router
from app.api.v1.endpoints.formas_pago import router as formas_pago_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.movimientos import router as movimientos_router
from app.api.v1.endpoints.parametros import router as parametros_router
from app.api.v1.endpoints.permisos import router as permisos_router
from app.api.v1.endpoints.propietarios import router as propietarios_router
from app.api.v1.endpoints.recepciones import router as recepciones_router
from app.api.v1.endpoints.sesiones import router as sesiones_router
from app.api.v1.endpoints.tareas import router as tareas_router
from app.api.v1.endpoints.tasas_impuesto import router as tasas_impuesto_router
from app.api.v1.endpoints.tipos_documento import router as tipos_documento_router
from app.api.v1.endpoints.tipos_gas import router as tipos_gas_router
from app.api.v1.endpoints.ubicaciones import router as ubicaciones_router
from app.api.v1.endpoints.usuarios import router as usuarios_router

api_router = APIRouter()

# ============================================================
# SIEMPRE ACTIVOS (sistema)
# ============================================================
api_router.include_router(health_router)

# ============================================================
# MÓDULOS (se habilitan por etapa)
# ============================================================
# Etapa 2 - Autenticación y seguridad:
#   auth (login/refresh/me) — subetapa 2.1: CRUD de usuarios, empleados,
#   tareas, permisos, sesiones y bitácora de auditoría.
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(usuarios_router, prefix="/usuarios")
api_router.include_router(empleados_router, prefix="/empleados")
api_router.include_router(tareas_router, prefix="/tareas")
api_router.include_router(permisos_router, prefix="/permisos")
api_router.include_router(sesiones_router, prefix="/sesiones")
api_router.include_router(auditoria_router, prefix="/auditoria")

# Etapa 3 - Datos maestros (subetapas 3.1 y 3.2): catálogos simples
# (áreas, categorías, tipos de gas, formas de pago, tipos de documento),
# parámetros del sistema y tasas de impuesto — dominio RBAC TAREA_29.
api_router.include_router(areas_router, prefix="/areas")
api_router.include_router(categorias_router, prefix="/categorias")
api_router.include_router(tipos_gas_router, prefix="/tipos-gas")
api_router.include_router(formas_pago_router, prefix="/formas-pago")
api_router.include_router(tipos_documento_router, prefix="/tipos-documento")
api_router.include_router(parametros_router, prefix="/parametros")
api_router.include_router(tasas_impuesto_router, prefix="/tasas-impuesto")

# Etapa 4 - Inventario de cilindros (subetapa 4.1: maestros restantes):
#   clientes (con receptores autorizados anidados) y propietarios —
#   dominios RBAC TAREA_01 y TAREA_02.
api_router.include_router(clientes_router, prefix="/clientes")
api_router.include_router(propietarios_router, prefix="/propietarios")

# Etapa 4 (cont.) - subetapa 4.2: cilindros (TAREA_03), ubicaciones
# (TAREA_29, catálogo) y movimientos (TAREA_15 ∨ TAREA_16) — el
# movimiento es la única vía de cambiar ubicación/estado de un cilindro.
api_router.include_router(ubicaciones_router, prefix="/ubicaciones")
api_router.include_router(cilindros_router, prefix="/cilindros")
api_router.include_router(movimientos_router, prefix="/movimientos")

# Etapa 5 - Operaciones (subetapa 5.1: recepción de cilindros):
#   /recepciones (TAREA_04) con detalles anidados; cada cilindro recibido
#   emite un movimiento (el estado del cilindro solo cambia vía Movimiento).
#   Pendientes: inspecciones, órdenes_llenado, ordenes_reparacion y
#   control_calidad.
api_router.include_router(recepciones_router, prefix="/recepciones")

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
