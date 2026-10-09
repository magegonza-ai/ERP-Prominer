"""
Endpoints de despacho y entregas de cilindros (ETAPA 5.5).

Colección `/entregas` (dominios RBAC TAREA_17 «Preparar entregas» /
TAREA_18 «Entregar cilindros»):

    | acción                     | RBAC                          |
    |----------------------------|-------------------------------|
    | leer (listar/detalle)      | TAREA_17 ∨ TAREA_18 + PERM_01 |
    | crear (BORRADOR)           | TAREA_17 + PERM_02            |
    | reemplazar (solo BORRADOR) | TAREA_17 + PERM_03            |
    | → PENDIENTE                | TAREA_17 + PERM_03            |
    | → CONFIRMADA               | TAREA_17 + PERM_06            |
    | → ENTREGADA                | TAREA_18 + PERM_06            |
    | → CANCELADA                | TAREA_17 + PERM_03            |

Ciclo de vida (una transición por endpoint, misma/inválida → 409 con
`allowed_states`):

    BORRADOR → PENDIENTE → CONFIRMADA → ENTREGADA   (terminales)
    BORRADOR/PENDIENTE → CANCELADA                  (terminal)

Cada cilindro debe estar despachable (RN13: `APROBADO` o
`LISTO_PARA_ENTREGAR`), pertenecer al propietario de la entrega y no
figurar en otra entrega activa (409 `DUPLICATE_VALUE`). Al pasar a
`ENTREGADA` se emite un `Movimiento` por cilindro **en la misma
transacción** (D31: el estado del cilindro solo cambia vía `Movimiento`;
origen = destino = ubicación actual, cambio puro de estado) que lo lleva a
`ENTREGADO`.

`CANCELADA` usa `TAREA_17 + PERM_03` (D36): la matriz sembrada de
TAREA_17/18 es `[0,1,2,5,7]` = PERM_01/02/03/06/08 y **no** otorga PERM_07
«Anular», así que la anulación se alcanza por transición con «modificar».
El `DELETE` de la cabecera no se expone (405): una entrega se anula por
estado. `EXCEPCION_DOC` y los documentos comerciales son de ETAPA
posterior (no alcanzables en 5.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

# noqa en TC001: FastAPI y las firmas resuelven estos nombres en runtime.
from app.api.deps import (  # noqa: TC001
    CurrentUser,
    RequireAnyTaskPermission,
    RequireTaskPermission,
    SessionDep,
)
from app.core.exceptions import (
    CylinderNotApprovedForDelivery,
    DuplicateValue,
    InvalidStateTransition,
    NotFound,
    ValidationError,
)
from app.core.numeracion import siguiente_numero
from app.core.permissions import require_permission, require_task
from app.models import (
    Cilindro,
    Cliente,
    DetalleEntrega,
    Entrega,
    Movimiento,
    Propietario,
)
from app.schemas.common import Pagina
from app.schemas.entregas import (
    DetalleEntregaCreate,
    EntregaCreate,
    EntregaEstadoUpdate,
    EntregaResponse,
    EntregaUpdate,
    EstadoEntrega,
)

router = APIRouter(tags=["Operaciones — despacho y entregas"])

# Lectura: cualquiera de las tareas del dominio de entregas.
_LEER = RequireAnyTaskPermission(("TAREA_17", "TAREA_18"), "PERM_01")
_CREAR = RequireTaskPermission("TAREA_17", "PERM_02")
_MODIFICAR = RequireTaskPermission("TAREA_17", "PERM_03")

# Estados de la entrega que mantienen "ocupados" sus cilindros.
_ESTADOS_ENTREGA_ACTIVA = ("BORRADOR", "PENDIENTE", "CONFIRMADA")

# Transiciones válidas por estado de origen.
_TRANSICIONES_VALIDAS = {
    "BORRADOR": ("PENDIENTE", "CANCELADA"),
    "PENDIENTE": ("CONFIRMADA", "CANCELADA"),
    "CONFIRMADA": ("ENTREGADA",),
}

# (tarea, permiso) exigidos para alcanzar cada estado (D36: CANCELADA usa
# PERM_03 porque la matriz sembrada de TAREA_17/18 no otorga PERM_07).
_GUARD_TRANSICION = {
    "PENDIENTE": ("TAREA_17", "PERM_03"),
    "CONFIRMADA": ("TAREA_17", "PERM_06"),
    "ENTREGADA": ("TAREA_18", "PERM_06"),
    "CANCELADA": ("TAREA_17", "PERM_03"),
}

# Prefijo del correlativo (D30).
_PREFIJO_NUMERO = "ENT"

# Carga eager de la cabecera + detalles + cilindros (evita lazy loads async).
_CARGA_ENTREGA = (
    selectinload(Entrega.detalles)
    .selectinload(DetalleEntrega.cilindro)
    .selectinload(Cilindro.tipo_gas),
    selectinload(Entrega.cliente_recibe),
    selectinload(Entrega.propietario),
)


def _respuesta(entrega: Entrega) -> EntregaResponse:
    return EntregaResponse.model_validate(entrega, from_attributes=True)


async def _exigir(session, user, tarea: str, permiso: str) -> None:
    """RBAC por transición: tarea (dominio) + permiso (acción)."""
    await require_task(session, user.id, tarea)
    await require_permission(session, user.id, permiso)


async def _obtener_entrega(session: SessionDep, entrega_id: uuid.UUID) -> Entrega:
    """
    Entrega con sus relaciones eager (si no existe → 404).

    `populate_existing` re-lee del registro actual aunque la instancia ya
    esté en el identity map (la sesión es `expire_on_commit=False`): sin esto,
    tras un PUT replace-all la colección `detalles` quedaría obsoleta en
    memoria y la respuesta reflejaría los cilindros anteriores.
    """
    stmt = (
        select(Entrega)
        .execution_options(populate_existing=True)
        .options(*_CARGA_ENTREGA)
        .where(Entrega.id == entrega_id)
    )
    entrega = (await session.execute(stmt)).scalar_one_or_none()
    if entrega is None:
        raise NotFound("Entrega", entrega_id)
    return entrega


async def _validar_cliente_activo(session: SessionDep, cliente_id: uuid.UUID) -> Cliente:
    cliente = await session.get(Cliente, cliente_id)
    if cliente is None:
        raise NotFound("Cliente", cliente_id)
    if cliente.estado != "ACTIVO":
        raise ValidationError(f"El cliente '{cliente.razon_social}' no está ACTIVO")
    return cliente


async def _validar_detalles(
    session: SessionDep,
    propietario_id: uuid.UUID,
    detalles: list[DetalleEntregaCreate],
    excluir_entrega_id: uuid.UUID | None = None,
) -> list:
    """
    Valida cada cilindro: existe (404), pertenece al propietario (400),
    está despachable —RN13— (422) y no está en otra entrega activa (409).
    Devuelve la lista de `Cilindro` en el mismo orden que `detalles`.
    """
    vistos: set[uuid.UUID] = set()
    validados: list = []
    for detalle in detalles:
        if detalle.cilindro_id in vistos:
            raise DuplicateValue("cilindro_id", str(detalle.cilindro_id))
        vistos.add(detalle.cilindro_id)

        cilindro = await session.get(Cilindro, detalle.cilindro_id)
        if cilindro is None:
            raise NotFound("Cilindro", detalle.cilindro_id)

        if cilindro.propietario_id != propietario_id:
            raise ValidationError(
                f"El cilindro '{cilindro.codigo_interno}' no pertenece al propietario de la entrega"
            )

        if cilindro.estado_operativo not in ("APROBADO", "LISTO_PARA_ENTREGAR"):
            raise CylinderNotApprovedForDelivery(cilindro.estado_operativo)

        stmt = (
            select(DetalleEntrega.id)
            .join(Entrega, Entrega.id == DetalleEntrega.entrega_id)
            .where(
                DetalleEntrega.cilindro_id == cilindro.id,
                Entrega.estado.in_(_ESTADOS_ENTREGA_ACTIVA),
            )
            .limit(1)
        )
        if excluir_entrega_id is not None:
            stmt = stmt.where(Entrega.id != excluir_entrega_id)
        ocupado = (await session.execute(stmt)).scalar_one_or_none()
        if ocupado is not None:
            raise DuplicateValue("cilindro_id", str(cilindro.id))

        validados.append(cilindro)
    return validados


def _montos(detalle: DetalleEntregaCreate) -> dict:
    """Calcula subtotal/impuesto_monto/total (cantidad fija 1; valorización posterior)."""
    base = Decimal("1") * Decimal(str(detalle.precio_unitario))
    descuento = (
        base * Decimal(str(detalle.descuento_pct)) / Decimal("100")
        + Decimal(str(detalle.descuento_monto))
    )
    subtotal = base - descuento
    impuesto = subtotal * Decimal(str(detalle.tasa_impuesto_pct)) / Decimal("100")
    total = subtotal + impuesto
    return {"subtotal": subtotal, "impuesto_monto": impuesto, "total": total}


# ============================================================
# ENTREGAS (cabecera)
# ============================================================


@router.get("", response_model=Pagina[EntregaResponse], summary="Listar entregas")
async def listar_entregas(
    session: SessionDep,
    user=Depends(_LEER),
    estado: EstadoEntrega | None = Query(None, description="Filtro exacto por estado."),
    cliente_recibe_id: uuid.UUID | None = Query(None),
    propietario_id: uuid.UUID | None = Query(None),
    desde: datetime | None = Query(None, description="Fecha de la entrega desde (inclusive)."),
    hasta: datetime | None = Query(None, description="Fecha de la entrega hasta (inclusive)."),
    q: str | None = Query(None, max_length=100, description="Contiene en el número."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=100),
):
    filtros = []
    if estado:
        filtros.append(Entrega.estado == estado)
    if cliente_recibe_id:
        filtros.append(Entrega.cliente_recibe_id == cliente_recibe_id)
    if propietario_id:
        filtros.append(Entrega.propietario_id == propietario_id)
    if desde:
        filtros.append(Entrega.fecha_hora >= desde)
    if hasta:
        filtros.append(Entrega.fecha_hora <= hasta)
    if q:
        filtros.append(Entrega.numero.ilike(f"%{q}%"))

    total = (
        await session.execute(select(func.count()).select_from(Entrega).where(*filtros))
    ).scalar_one()
    filas = (
        await session.execute(
            select(Entrega)
            .options(*_CARGA_ENTREGA)
            .where(*filtros)
            .order_by(Entrega.fecha_hora.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
    ).scalars().all()

    return Pagina[EntregaResponse](
        items=[_respuesta(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        paginas=max(1, -(-total // por_pagina)),
    )


@router.get("/{entrega_id}", response_model=EntregaResponse, summary="Detalle de entrega")
async def obtener_entrega(
    entrega_id: uuid.UUID,
    session: SessionDep,
    user=Depends(_LEER),
) -> EntregaResponse:
    return _respuesta(await _obtener_entrega(session, entrega_id))


@router.post(
    "",
    response_model=EntregaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear entrega con sus cilindros (numero del servidor)",
)
async def crear_entrega(
    body: EntregaCreate,
    session: SessionDep,
    user=Depends(_CREAR),
) -> EntregaResponse:
    cliente = await _validar_cliente_activo(session, body.cliente_recibe_id)
    propietario = await session.get(Propietario, body.propietario_id)
    if propietario is None:
        raise NotFound("Propietario", body.propietario_id)

    await _validar_detalles(session, propietario.id, body.detalles)

    entrega = Entrega(
        numero=await siguiente_numero(session, Entrega, "numero", _PREFIJO_NUMERO),
        estado="BORRADOR",
        usuario_responsable_id=user.id,
        cliente_recibe_id=cliente.id,
        propietario_id=propietario.id,
        receptor_nombre=body.receptor_nombre,
        receptor_rut=body.receptor_rut,
        receptor_relacion=body.receptor_relacion,
        observaciones=body.observaciones,
    )
    session.add(entrega)
    await session.flush()

    for detalle in body.detalles:
        session.add(
            DetalleEntrega(
                entrega_id=entrega.id,
                cilindro_id=detalle.cilindro_id,
                cantidad=1,
                **detalle.model_dump(exclude={"cilindro_id"}),
                **_montos(detalle),
            )
        )

    await session.commit()
    return _respuesta(await _obtener_entrega(session, entrega.id))


@router.put(
    "/{entrega_id}",
    response_model=EntregaResponse,
    summary="Reemplazar cabecera y cilindros de la entrega (solo en BORRADOR)",
)
async def reemplazar_entrega(
    entrega_id: uuid.UUID,
    body: EntregaUpdate,
    session: SessionDep,
    user=Depends(_MODIFICAR),
) -> EntregaResponse:
    entrega = await _obtener_entrega(session, entrega_id)

    if entrega.estado != "BORRADOR":
        raise ValidationError(
            f"La entrega '{entrega.numero}' está '{entrega.estado}': solo se edita en 'BORRADOR'"
        )

    cliente = await _validar_cliente_activo(session, body.cliente_recibe_id)
    propietario = await session.get(Propietario, body.propietario_id)
    if propietario is None:
        raise NotFound("Propietario", body.propietario_id)

    # Reemplazo total (replace-all): los cilindros propios se excluyen del
    # chequeo "en otra entrega activa" para permitir conservarlos.
    await _validar_detalles(session, propietario.id, body.detalles, excluir_entrega_id=entrega.id)

    for detalle in list(entrega.detalles):
        await session.delete(detalle)
    await session.flush()

    entrega.cliente_recibe_id = cliente.id
    entrega.propietario_id = propietario.id
    entrega.receptor_nombre = body.receptor_nombre
    entrega.receptor_rut = body.receptor_rut
    entrega.receptor_relacion = body.receptor_relacion
    entrega.observaciones = body.observaciones

    for detalle in body.detalles:
        session.add(
            DetalleEntrega(
                entrega_id=entrega.id,
                cilindro_id=detalle.cilindro_id,
                cantidad=1,
                **detalle.model_dump(exclude={"cilindro_id"}),
                **_montos(detalle),
            )
        )

    await session.commit()
    return _respuesta(await _obtener_entrega(session, entrega.id))


@router.patch(
    "/{entrega_id}/estado",
    response_model=EntregaResponse,
    summary="Cambiar estado de la entrega (emite movimientos atómicos)",
)
async def cambiar_estado(
    entrega_id: uuid.UUID,
    body: EntregaEstadoUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EntregaResponse:
    entrega = await _obtener_entrega(session, entrega_id)

    permitidas = _TRANSICIONES_VALIDAS.get(entrega.estado, ())
    if body.estado not in permitidas:
        raise InvalidStateTransition(
            "Entrega", entrega.estado, body.estado, allowed=list(permitidas)
        )

    tarea, permiso = _GUARD_TRANSICION[body.estado]
    await _exigir(session, user, tarea, permiso)

    # D31: al ENTREGAR, el cilindro pasa a ENTREGADO vía Movimiento
    # (misma transacción; cambio puro de estado, origen = destino).
    if body.estado == "ENTREGADA":
        for detalle in entrega.detalles:
            cilindro = detalle.cilindro
            session.add(
                Movimiento(
                    cilindro_id=cilindro.id,
                    ubicacion_origen_id=cilindro.ubicacion_actual_id,
                    ubicacion_destino_id=cilindro.ubicacion_actual_id,
                    estado_anterior=cilindro.estado_operativo,
                    estado_nuevo="ENTREGADO",
                    usuario_entrega_id=user.id,
                    motivo=body.motivo or f"Entrega {entrega.numero}",
                )
            )
            cilindro.estado_operativo = "ENTREGADO"

    entrega.estado = body.estado
    if body.receptor_nombre is not None:
        entrega.receptor_nombre = body.receptor_nombre
    if body.receptor_rut is not None:
        entrega.receptor_rut = body.receptor_rut
    if body.receptor_relacion is not None:
        entrega.receptor_relacion = body.receptor_relacion
    if body.firma_confirmacion_url is not None:
        entrega.firma_confirmacion_url = body.firma_confirmacion_url
    if body.firma_tipo is not None:
        entrega.firma_tipo = body.firma_tipo
    if body.observaciones is not None:
        entrega.observaciones = body.observaciones

    await session.commit()
    return _respuesta(await _obtener_entrega(session, entrega.id))
