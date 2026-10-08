"""
Endpoints de sesiones (ETAPA 2.1, solo lectura + revocación).

Dominio RBAC: **TAREA_28** (administrar usuarios). Acciones: PERM_01
consultar, PERM_07 anular (revocar).

Revocar una sesión invalida su refresh token de inmediato: el usuario
deberá iniciar sesión de nuevo (los access tokens vivos siguen siendo
válidos hasta expirar, ≤15 min, o hasta que cambie el estado de cuenta).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
    ip_a_cadena,
    obtener_o_404,
)
from app.core.exceptions import NotFound
from app.models import Sesion, Usuario
from app.schemas.common import Pagina
from app.schemas.sesiones import SesionResponse

router = APIRouter(tags=["Sesiones"])

# Guard RBAC por acción (dominio TAREA_28).
_LEER = RequireTaskPermission("TAREA_28", "PERM_01")
_ANULAR = RequireTaskPermission("TAREA_28", "PERM_07")


def _respuesta(sesion: Sesion, username: str | None = None) -> SesionResponse:
    return SesionResponse(
        id=sesion.id,
        usuario_id=sesion.usuario_id,
        usuario_username=username,
        iniciada_en=sesion.iniciada_en,
        ultima_actividad=sesion.ultima_actividad,
        expira_en=sesion.expira_en,
        revocada=sesion.revocada,
        revocada_en=sesion.revocada_en,
        revocada_por=sesion.revocada_por,
        ip_inicio=ip_a_cadena(sesion.ip_inicio),
        ip_ultima=ip_a_cadena(sesion.ip_ultima),
        user_agent=sesion.user_agent,
    )


@router.get("", response_model=Pagina[SesionResponse], summary="Listar sesiones")
async def listar_sesiones(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    usuario_id: uuid.UUID | None = Query(None, description="Filtro por usuario."),
    activas: bool | None = Query(
        None, description="true = solo vivas; false = revocadas o expiradas; omitir = todas."
    ),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[SesionResponse]:
    filtros = []
    if usuario_id is not None:
        filtros.append(Sesion.usuario_id == usuario_id)
    ahora = datetime.now(UTC)
    if activas is True:
        filtros.extend([Sesion.revocada.is_(False), Sesion.expira_en > ahora])
    elif activas is False:
        filtros.append(or_(Sesion.revocada.is_(True), Sesion.expira_en <= ahora))

    total = (
        await session.execute(select(func.count()).select_from(Sesion).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Sesion, Usuario.username)
            .join(Usuario, Usuario.id == Sesion.usuario_id, isouter=True)
            .where(*filtros)
            .order_by(Sesion.ultima_actividad.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).all()

    return Pagina[SesionResponse](
        items=[_respuesta(s, username) for s, username in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{sesion_id}", response_model=SesionResponse, summary="Detalle de sesión")
async def obtener_sesion(
    sesion_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> SesionResponse:
    fila = (
        await session.execute(
            select(Sesion, Usuario.username)
            .join(Usuario, Usuario.id == Sesion.usuario_id, isouter=True)
            .where(Sesion.id == sesion_id)
        )
    ).one_or_none()
    if fila is None:
        raise NotFound("Sesión", sesion_id)
    return _respuesta(fila[0], fila[1])


@router.delete(
    "/{sesion_id}",
    response_model=SesionResponse,
    summary="Revocar sesión (idempotente)",
)
async def revocar_sesion(
    sesion_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
) -> SesionResponse:
    """Marca la sesión como revocada. Si ya estaba revocada, se devuelve
    igualmente (200, operación idempotente)."""
    sesion = await obtener_o_404(session, Sesion, sesion_id, "Sesión")
    if not sesion.revocada:
        sesion.revocada = True
        sesion.revocada_en = datetime.now(UTC)
        sesion.revocada_por = user.id
        await session.commit()
        await session.refresh(sesion)

    username = (
        await session.execute(select(Usuario.username).where(Usuario.id == sesion.usuario_id))
    ).scalar_one_or_none()
    return _respuesta(sesion, username)
