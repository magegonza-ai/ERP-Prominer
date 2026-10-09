"""
Paquete de modelos SQLAlchemy - Exporta todos los modelos.
"""

from __future__ import annotations

from app.models.audit import (
    Auditoria,
    Cliente,
    ClienteReceptorAutorizado,
    DocumentoAdjunto,
    Fotografia,
    Notificacion,
    Propietario,
)
from app.models.base import AuditMixin, Base, BaseModel, SoftDeleteMixin, TimestampMixin, UserTrackingMixin
from app.models.commercial import (
    DetalleListaPrecios,
    DetallePresupuesto,
    DetalleValorizacion,
    ListaPrecios,
    Presupuesto,
    Producto,
    Servicio,
    Valorizacion,
)
from app.models.cylinder import (
    Cilindro,
    ControlCalidad,
    DetalleRecepcion,
    Inspeccion,
    Movimiento,
    Recepcion,
    Ubicacion,
)
from app.models.delivery import (
    CambioPropietario,
    DetalleEntrega,
    DocumentoComercial,
    Entrega,
    Pago,
)
from app.models.devoluciones import Devolucion, DevolucionDetalle
from app.models.master_data import (
    Area,
    Categoria,
    Empleado,
    EmpleadoTarea,
    FormaPago,
    Parametro,
    Permiso,
    Sesion,
    Tarea,
    TareaPermiso,
    TasaImpuesto,
    TipoDocumento,
    TipoGas,
    Usuario,
)
from app.models.operations import (
    DetalleOrden,
    OrdenTrabajo,
    TareaAsignada,
)

__all__ = [
    # Base
    "Base",
    "BaseModel",
    "AuditMixin",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UserTrackingMixin",
    # Master data
    "Area",
    "Categoria",
    "TipoGas",
    "FormaPago",
    "TipoDocumento",
    "Parametro",
    "TasaImpuesto",
    "Empleado",
    "Usuario",
    "Sesion",
    "Tarea",
    "Permiso",
    "TareaPermiso",
    "EmpleadoTarea",
    # Cylinder
    "Ubicacion",
    "Cilindro",
    "Movimiento",
    "Recepcion",
    "DetalleRecepcion",
    "Inspeccion",
    "ControlCalidad",
    # Operations
    "OrdenTrabajo",
    "DetalleOrden",
    "TareaAsignada",
    # Commercial
    "Producto",
    "Servicio",
    "ListaPrecios",
    "DetalleListaPrecios",
    "Presupuesto",
    "DetallePresupuesto",
    "Valorizacion",
    "DetalleValorizacion",
    # Delivery
    "Entrega",
    "DetalleEntrega",
    "DocumentoComercial",
    "Pago",
    "CambioPropietario",
    # Devoluciones
    "Devolucion",
    "DevolucionDetalle",
    # Audit
    "Propietario",
    "Cliente",
    "ClienteReceptorAutorizado",
    "Auditoria",
    "Fotografia",
    "DocumentoAdjunto",
    "Notificacion",
]
