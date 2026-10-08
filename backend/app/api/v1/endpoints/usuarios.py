"""
Endpoints de usuarios (ETAPA 2.1).

Dominio RBAC: **TAREA_28** (administrar usuarios). Acciones: PERM_01
consultar, PERM_02 crear, PERM_03 modificar, PERM_07 anular.

DELETE /usuarios/{id} es una **anulación lógica** (estado := BLOQUEADO más
revocación de todas las sesiones activas): no existe borrado físico para
conservar la trazabilidad. Toda transición de estado distinta de ACTIVO
también revoca las sesiones vivas (la cuenta queda inaccesible).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select, update

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    RequireTaskPermission,
    SessionDep,
    obtener_o_404,
    verificar_unico,
)
from app.core.exceptions import (
    InvalidStateTransition,
    PasswordPolicyError,
    ValidationError,
)
from app.core.security import hash_password, validate_password_policy
from app.models import Empleado, Sesion, Usuario
from app.schemas.common import Pagina
from app.schemas.usuarios import (
    TODOS_ESTADOS_USUARIO,
    UsuarioCreate,
    UsuarioEstadoUpdate,
    UsuarioPasswordUpdate,
    UsuarioResponse,
    UsuarioUpdate,
)

router = APIRouter(tags=["Usuarios"])

# Guard RBAC por acción (dominio TAREA_28).
_LEER = RequireTaskPermission("TAREA_28", "PERM_01")
_CREAR = RequireTaskPermission("TAREA_28", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_28", "PERM_03")
_ANULAR = RequireTaskPermission("TAREA_28", "PERM_07")


async def _revocar_sesiones(session, usuario_id: uuid.UUID, revocado_por: uuid.UUID) -> int:
    """Revoca todas las sesiones vivas de un usuario. Devuelve cuántas."""
    result = await session.execute(
        update(Sesion)
        .where(Sesion.usuario_id == usuario_id, Sesion.revocada.is_(False))
        .values(revocada=True, revocada_en=datetime.now(UTC), revocada_por=revocado_por)
    )
    return result.rowcount or 0


def _respuesta(usuario: Usuario) -> UsuarioResponse:
    return UsuarioResponse.model_validate(usuario, from_attributes=True)


@router.get("", response_model=Pagina[UsuarioResponse], summary="Listar usuarios")
async def listar_usuarios(
    session: SessionDep,
    user: Usuario = Depends(_LEER),
    estado: str | None = Query(None, description="Filtro exacto por estado de cuenta."),
    q: str | None = Query(None, max_length=100, description="Contiene en username o email."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
) -> Pagina[UsuarioResponse]:
    filtros = []
    if estado:
        filtros.append(Usuario.estado == estado)
    if q:
        patron = f"%{q}%"
        filtros.append(or_(Usuario.username.ilike(patron), Usuario.email.ilike(patron)))

    total = (
        await session.execute(select(func.count()).select_from(Usuario).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Usuario)
            .where(*filtros)
            .order_by(Usuario.username)
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[UsuarioResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{usuario_id}", response_model=UsuarioResponse, summary="Detalle de usuario")
async def obtener_usuario(
    usuario_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_LEER),
) -> UsuarioResponse:
    return _respuesta(await obtener_o_404(session, Usuario, usuario_id, "Usuario"))


@router.post(
    "",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear usuario",
)
async def crear_usuario(
    body: UsuarioCreate,
    session: SessionDep,
    user: Usuario = Depends(_CREAR),
) -> UsuarioResponse:
    valida, errores = validate_password_policy(body.password)
    if not valida:
        raise PasswordPolicyError(errores)

    await verificar_unico(session, Usuario, "username", body.username)
    await verificar_unico(session, Usuario, "email", body.email)
    if body.empleado_id is not None:
        await obtener_o_404(session, Empleado, body.empleado_id, "Empleado")
        await verificar_unico(session, Usuario, "empleado_id", body.empleado_id)

    usuario = Usuario(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        estado=body.estado or "PENDIENTE_ACTIVACION",
        empleado_id=body.empleado_id,
        requiere_cambio_password=body.requiere_cambio_password,
    )
    session.add(usuario)
    await session.commit()
    await session.refresh(usuario)
    return _respuesta(usuario)


@router.patch("/{usuario_id}", response_model=UsuarioResponse, summary="Actualizar usuario")
async def actualizar_usuario(
    usuario_id: uuid.UUID,
    body: UsuarioUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> UsuarioResponse:
    usuario = await obtener_o_404(session, Usuario, usuario_id, "Usuario")

    # `null` = sin cambio (contrato de UsuarioUpdate): se filtra antes de validar.
    datos = {
        campo: valor
        for campo, valor in body.model_dump(exclude_unset=True).items()
        if valor is not None
    }
    if not datos:
        raise ValidationError("No se indicó ningún campo para actualizar")

    if "username" in datos:
        await verificar_unico(session, Usuario, "username", datos["username"], exclude_id=usuario_id)
    if "email" in datos:
        await verificar_unico(session, Usuario, "email", datos["email"], exclude_id=usuario_id)
    if datos.get("empleado_id") is not None:
        await obtener_o_404(session, Empleado, datos["empleado_id"], "Empleado")
        await verificar_unico(session, Usuario, "empleado_id", datos["empleado_id"], exclude_id=usuario_id)

    for campo, valor in datos.items():
        setattr(usuario, campo, valor)

    await session.commit()
    await session.refresh(usuario)
    return _respuesta(usuario)


@router.patch("/{usuario_id}/estado", response_model=UsuarioResponse, summary="Cambiar estado de cuenta")
async def cambiar_estado(
    usuario_id: uuid.UUID,
    body: UsuarioEstadoUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> UsuarioResponse:
    usuario = await obtener_o_404(session, Usuario, usuario_id, "Usuario")

    if usuario.estado == body.estado:
        raise InvalidStateTransition(
            "Usuario",
            usuario.estado,
            body.estado,
            allowed=[e for e in TODOS_ESTADOS_USUARIO if e != usuario.estado],
        )

    usuario.estado = body.estado
    if body.estado == "ACTIVO":
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None
    else:
        # Un estado no-ACTIVO inhabilita el acceso: además se revocan las
        # sesiones vivas por si el token sigue siendo válido en algún cliente.
        await _revocar_sesiones(session, usuario.id, user.id)

    await session.commit()
    await session.refresh(usuario)
    return _respuesta(usuario)


@router.put("/{usuario_id}/password", response_model=UsuarioResponse, summary="Reseteo de contraseña")
async def resetear_password(
    usuario_id: uuid.UUID,
    body: UsuarioPasswordUpdate,
    session: SessionDep,
    user: Usuario = Depends(_MODIFICAR),
) -> UsuarioResponse:
    """Reseteo por administrador: aplica la política, limpia el bloqueo,
    exige cambio en el próximo login y revoca las sesiones vivas."""
    usuario = await obtener_o_404(session, Usuario, usuario_id, "Usuario")

    valida, errores = validate_password_policy(body.password)
    if not valida:
        raise PasswordPolicyError(errores)

    usuario.password_hash = hash_password(body.password)
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    usuario.requiere_cambio_password = True
    await _revocar_sesiones(session, usuario.id, user.id)

    await session.commit()
    await session.refresh(usuario)
    return _respuesta(usuario)


@router.delete("/{usuario_id}", response_model=UsuarioResponse, summary="Anular usuario (lógico)")
async def anular_usuario(
    usuario_id: uuid.UUID,
    session: SessionDep,
    user: Usuario = Depends(_ANULAR),
) -> UsuarioResponse:
    """Anulación lógica: estado := BLOQUEADO + revocación de sesiones."""
    usuario = await obtener_o_404(session, Usuario, usuario_id, "Usuario")
    usuario.estado = "BLOQUEADO"
    await _revocar_sesiones(session, usuario.id, user.id)
    await session.commit()
    await session.refresh(usuario)
    return _respuesta(usuario)
