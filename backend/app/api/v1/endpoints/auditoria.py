"""
Endpoints de auditoría (ETAPA 2.1, SOLO LECTURA).

Dominio RBAC: **TAREA_30** (revisar auditoría) + PERM_01 consultar.
La tabla `auditoria` es inmutable: la escriben los triggers de BD, así que
este módulo no expone POST/PATCH/DELETE.

`GET /auditoria` pagina (orden fecha_hora DESC) y filtra por módulo,
acción, registro, usuario y rango de fechas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
    ip_a_cadena,
    obtener_o_404,
)
from app.models import Auditoria, Usuario
from app.schemas.auditoria import AuditoriaResponse
from app.schemas.common import Pagina

router = APIRouter(tags=["Auditoría"])

# Dominio RBAC: solo la tarea de auditoría (TAREA_30).
_LEER = RequireTaskPermission("TAREA_30", "PERM_01")


def _respuesta(registro: Auditoria) -> AuditoriaResponse:
    return AuditoriaResponse(
        id=registro.id,
        usuario_id=registro.usuario_id,
        fecha_hora=registro.fecha_hora,
        modulo=registro.modulo,
        accion=registro.accion,
        registro_afectado_id=registro.registro_afectado_id,
        registro_tipo=registro.registro_tipo,
        valor_anterior=registro.valor_anterior,
        valor_nuevo=registro.valor_nuevo,
        motivo=registro.motivo,
        ip=ip_a_cadena(registro.ip),
        user_agent=registro.user_agent,
    )


@router.get("", response_model=Pagina[AuditoriaResponse], summary="Bitácora de auditoría")
async def listar_auditoria(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    modulo: str | None = Query(None, description="Filtro exacto por módulo."),
    accion: str | None = Query(None, description="Filtro exacto por acción (ck_auditoria_accion)."),
    registro_tipo: str | None = Query(None, description="Filtro exacto por tipo de tabla."),
    usuario_id: uuid.UUID | None = Query(None, description="Usuario que ejecutó la acción."),
    fecha_desde: datetime | None = Query(None, description="Inclusivo (ISO 8601)."),
    fecha_hasta: datetime | None = Query(None, description="Inclusivo (ISO 8601)."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[AuditoriaResponse]:
    filtros = []
    if modulo:
        filtros.append(Auditoria.modulo == modulo)
    if accion:
        filtros.append(Auditoria.accion == accion)
    if registro_tipo:
        filtros.append(Auditoria.registro_tipo == registro_tipo)
    if usuario_id is not None:
        filtros.append(Auditoria.usuario_id == usuario_id)
    if fecha_desde is not None:
        filtros.append(Auditoria.fecha_hora >= fecha_desde)
    if fecha_hasta is not None:
        filtros.append(Auditoria.fecha_hora <= fecha_hasta)

    total = (
        await session.execute(select(func.count()).select_from(Auditoria).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Auditoria)
            .where(*filtros)
            .order_by(Auditoria.fecha_hora.desc(), Auditoria.id.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[AuditoriaResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{registro_id}", response_model=AuditoriaResponse, summary="Detalle de auditoría")
async def obtener_registro(
    registro_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> AuditoriaResponse:
    registro = await obtener_o_404(session, Auditoria, registro_id, "Registro de auditoría")
    return _respuesta(registro)
