"""
Tests de la subetapa 5.4: control de calidad de cilindros.

Control de calidad (TAREA_14): **append-only** (POST + GET; PATCH/DELETE →
405), `usuario_id` = usuario autenticado y `fecha_hora` del servidor. En 5.4
el control se registra sobre un cilindro de una orden en `PENDIENTE_CALIDAD`
(cilindro `PENDIENTE_CONTROL_CALIDAD`); el `resultado` mapea al
`estado_operativo` del cilindro vía `Movimiento` atómico (D31):

    APROBADO                   -> LISTO_PARA_ENTREGAR (si autoriza_entrega) o APROBADO
    APROBADO_OBSERVACIONES     -> APROBADO_OBSERVACIONES
    REQUIERE_NUEVA_REPARACION  -> APTO_REPARACION
    RECHAZADO                  -> RECHAZADO
    PENDIENTE_REVISION         -> sin cambio (permite un nuevo control)

La orden **cierra** (misma transacción) cuando todos sus cilindros quedan
controlados y ninguno en `PENDIENTE_REVISION`: `RECHAZADA` ›
`REQUIERE_NUEVA_REPARACION` › `APROBADA`. Además del permiso PERM_02, el
resultado exige PERM_04 (aprobar) o PERM_05 (rechazar), y se aplica la
segregación de funciones RN28 (403 `SEPARATION_OF_DUTIES` si quien controla
fue quien ejecutó el trabajo del cilindro).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from factories import (
    TAREA_CONTROL_CALIDAD,
    TAREA_LLENADO_CERRAR,
    TAREA_LLENADO_CREAR,
    TAREA_LLENADO_EJECUTAR,
    TAREA_RECEPCION,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    prefijo,
    token_de,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import (
    Area,
    Cilindro,
    Movimiento,
    OrdenTrabajo,
    Permiso,
    Propietario,
    Tarea,
    TareaAsignada,
    TareaPermiso,
    TipoGas,
    Ubicacion,
    Usuario,
)

_RUTA_CC = "/api/v1/controles-calidad"
_RUTA_OT = "/api/v1/ordenes-trabajo"
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_04", "PERM_05", "PERM_06", "PERM_07"]


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _dominio(session_factory, *tareas: str):
    return await crear_cadena_rbac(session_factory, tareas=list(tareas), permisos=_PERMISOS)


# ============================================================
# HELPERS DE FIXTURES (directo en BD)
# ============================================================


async def _base(session_factory, *, estados=("APTO_LLENADO",)) -> dict:
    """Crea propietario, tipo de gas, ubicación, área y N cilindros."""
    p = prefijo()
    async with session_factory() as session:
        propietario = Propietario(tipo="AGAS", rut=f"2{p[:8]}", razon_social=f"Prop {p[:6]}")
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        ubicacion = Ubicacion(codigo=f"UB{p[:10]}", nombre=f"Bodega {p[:6]}", tipo="INTERNA")
        area = Area(codigo=f"AR{p[:10]}", nombre=f"Área {p[:6]}")
        session.add_all([propietario, tipo_gas, ubicacion, area])
        await session.flush()

        cilindros = []
        for i, estado in enumerate(estados):
            cilindro = Cilindro(
                codigo_interno=f"CI{p[:8]}{i:02d}",
                numero_serie=f"NS{p[:8]}{i:02d}",
                codigo_qr=f"QR{p[:8]}{i:02d}",
                propietario_id=propietario.id,
                tipo_gas_id=tipo_gas.id,
                capacidad_kg=42,
                ubicacion_actual_id=ubicacion.id,
                estado_operativo=estado,
            )
            session.add(cilindro)
            cilindros.append(cilindro)
        await session.flush()
        await session.commit()
        return {
            "area_id": area.id,
            "cilindros": [c.id for c in cilindros],
        }


async def _ctx_cc(session_factory, *, estados=("APTO_LLENADO",)):
    """Usuario que crea la orden, la ejecuta y hace el control de calidad."""
    user, clave = await _dominio(
        session_factory,
        TAREA_LLENADO_CREAR,
        TAREA_LLENADO_EJECUTAR,
        TAREA_LLENADO_CERRAR,
        TAREA_CONTROL_CALIDAD,
    )
    datos = await _base(session_factory, estados=estados)
    return user, clave, datos


def _body_orden(area_id, cilindros) -> dict:
    return {
        "tipo": "LLENADO",
        "area_responsable_id": str(area_id),
        "detalles": [{"cilindro_id": str(c)} for c in cilindros],
    }


def _orden_en_calidad(client: TestClient, headers: dict, datos: dict) -> str:
    """Crea la orden de llenado y la lleva hasta PENDIENTE_CALIDAD."""
    resp = client.post(_RUTA_OT, headers=headers, json=_body_orden(datos["area_id"], datos["cilindros"]))
    assert resp.status_code == 201, resp.text
    orden_id = resp.json()["id"]
    for estado in ("EN_PROCESO", "FINALIZADA", "PENDIENTE_CALIDAD"):
        resp = client.patch(
            f"{_RUTA_OT}/{orden_id}/estado", headers=headers, json={"estado": estado}
        )
        assert resp.status_code == 200, resp.text
    return orden_id


def _body_cc(cilindro_id, orden_id, resultado: str, **extra) -> dict:
    body = {
        "cilindro_id": str(cilindro_id),
        "orden_relacionada_id": str(orden_id),
        "resultado": resultado,
    }
    body.update(extra)
    return body


async def _set_matriz(session_factory, codigo_tarea: str, codigo_permiso: str, concedido: bool) -> bool:
    """Concede/revoca un permiso en la tarea; devuelve el valor anterior."""
    async with session_factory() as session:
        tarea = (
            await session.execute(select(Tarea).where(Tarea.codigo == codigo_tarea))
        ).scalar_one()
        permiso = (
            await session.execute(select(Permiso).where(Permiso.codigo == codigo_permiso))
        ).scalar_one()
        fila = (
            await session.execute(
                select(TareaPermiso).where(
                    TareaPermiso.tarea_id == tarea.id,
                    TareaPermiso.permiso_id == permiso.id,
                )
            )
        ).scalar_one()
        anterior = fila.concedido
        fila.concedido = concedido
        await session.commit()
        return anterior


# ============================================================
# GUARDS RBAC
# ============================================================


def test_cc_sin_autenticacion_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA_CC)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


async def test_cc_dominio_equivocado_403(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA_CC, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


async def test_cc_sin_permiso_crear_403(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    solo14, clave14 = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CONTROL_CALIDAD], permisos=_PERMISOS
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        anterior = await _set_matriz(session_factory, TAREA_CONTROL_CALIDAD, "PERM_02", False)
        try:
            hb = _admin(client, solo14, clave14)
            resp = client.post(
                _RUTA_CC, headers=hb, json=_body_cc(datos["cilindros"][0], orden_id, "APROBADO")
            )
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_02" in resp.json()["detail"]["message"]
        finally:
            await _set_matriz(session_factory, TAREA_CONTROL_CALIDAD, "PERM_02", bool(anterior))


async def test_cc_permiso_aprobar_rechazar_403(session_factory) -> None:
    """Además de PERM_02, aprobar exige PERM_04 y rechazar exige PERM_05."""
    user, clave, datos = await _ctx_cc(session_factory)
    solo14, clave14 = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CONTROL_CALIDAD], permisos=_PERMISOS
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        cid = datos["cilindros"][0]

        anterior = await _set_matriz(session_factory, TAREA_CONTROL_CALIDAD, "PERM_04", False)
        try:
            hb = _admin(client, solo14, clave14)
            resp = client.post(_RUTA_CC, headers=hb, json=_body_cc(cid, orden_id, "APROBADO"))
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_04" in resp.json()["detail"]["message"]
        finally:
            await _set_matriz(session_factory, TAREA_CONTROL_CALIDAD, "PERM_04", bool(anterior))

        anterior = await _set_matriz(session_factory, TAREA_CONTROL_CALIDAD, "PERM_05", False)
        try:
            hb = _admin(client, solo14, clave14)
            resp = client.post(_RUTA_CC, headers=hb, json=_body_cc(cid, orden_id, "RECHAZADO"))
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_05" in resp.json()["detail"]["message"]
        finally:
            await _set_matriz(session_factory, TAREA_CONTROL_CALIDAD, "PERM_05", bool(anterior))


# ============================================================
# ALTA + MOVIMIENTO + CIERRE DE LA ORDEN
# ============================================================


async def test_cc_alta_completa_movimiento_y_cierre(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        cid = datos["cilindros"][0]

        resp = client.post(
            _RUTA_CC,
            headers=headers,
            json=_body_cc(
                cid,
                orden_id,
                "APROBADO",
                presion_ok=True,
                peso_ok=True,
                fuga_ok=False,
                etiquetado_ok=True,
                pintura_ok=True,
                accesorios_ok=True,
                documentacion_ok=True,
                observaciones="Llenado conforme",
                fotografias={"frontal": "ok"},
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["usuario_id"] == str(user.id)
        assert data["fecha_hora"] is not None
        assert data["resultado"] == "APROBADO"
        assert data["autoriza_entrega"] is False
        assert data["presion_ok"] is True
        assert data["observaciones"] == "Llenado conforme"
        assert data["fotografias"] == {"frontal": "ok"}
        assert data["orden_relacionada_id"] == orden_id
        cc_id = data["id"]

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cid)
            assert cilindro.estado_operativo == "APROBADO"
            movimientos = (
                await session.execute(
                    select(Movimiento)
                    .where(Movimiento.cilindro_id == cid)
                    .order_by(Movimiento.fecha_hora)
                )
            ).scalars().all()
            assert [m.estado_nuevo for m in movimientos] == [
                "EN_PROCESO_LLENADO",
                "FINALIZADO_LLENADO",
                "PENDIENTE_CONTROL_CALIDAD",
                "APROBADO",
            ]
            assert movimientos[-1].estado_anterior == "PENDIENTE_CONTROL_CALIDAD"
            assert "APROBADO" in movimientos[-1].motivo
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "APROBADA"

        # Detalle y listado con filtros.
        assert client.get(f"{_RUTA_CC}/{cc_id}", headers=headers).status_code == 200
        resp = client.get(
            _RUTA_CC,
            headers=headers,
            params={
                "cilindro_id": str(cid),
                "orden_relacionada_id": orden_id,
                "resultado": "APROBADO",
                "usuario_id": str(user.id),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == cc_id


async def test_cc_autoriza_entrega_listo_para_entregar(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        cid = datos["cilindros"][0]

        resp = client.post(
            _RUTA_CC, headers=headers, json=_body_cc(cid, orden_id, "APROBADO", autoriza_entrega=True)
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["autoriza_entrega"] is True

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cid)
            assert cilindro.estado_operativo == "LISTO_PARA_ENTREGAR"
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "APROBADA"


@pytest.mark.parametrize(
    ("resultado", "estado_cilindro", "estado_orden"),
    [
        ("APROBADO_OBSERVACIONES", "APROBADO_OBSERVACIONES", "APROBADA"),
        ("REQUIERE_NUEVA_REPARACION", "APTO_REPARACION", "REQUIERE_NUEVA_REPARACION"),
        ("RECHAZADO", "RECHAZADO", "RECHAZADA"),
    ],
)
async def test_cc_mapeo_resultado_y_cierre(
    session_factory, resultado: str, estado_cilindro: str, estado_orden: str
) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        cid = datos["cilindros"][0]

        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(cid, orden_id, resultado))
        assert resp.status_code == 201, resp.text

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cid)
            assert cilindro.estado_operativo == estado_cilindro
            movimiento = (
                await session.execute(
                    select(Movimiento)
                    .where(Movimiento.cilindro_id == cid)
                    .order_by(Movimiento.fecha_hora)
                )
            ).scalars().all()[-1]
            assert movimiento.estado_anterior == "PENDIENTE_CONTROL_CALIDAD"
            assert movimiento.estado_nuevo == estado_cilindro
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == estado_orden


async def test_cc_pendiente_revision_no_cierra_y_permite_recontrol(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        cid = datos["cilindros"][0]

        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(cid, orden_id, "PENDIENTE_REVISION"))
        assert resp.status_code == 201, resp.text

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cid)
            assert cilindro.estado_operativo == "PENDIENTE_CONTROL_CALIDAD"
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "PENDIENTE_CALIDAD"
            movimiento = (
                await session.execute(
                    select(Movimiento)
                    .where(Movimiento.cilindro_id == cid)
                    .order_by(Movimiento.fecha_hora)
                )
            ).scalars().all()[-1]
            assert movimiento.estado_nuevo == "PENDIENTE_CONTROL_CALIDAD"

        # Re-control (el cilindro sigue controlable) → la orden cierra.
        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(cid, orden_id, "APROBADO"))
        assert resp.status_code == 201, resp.text
        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cid)
            assert cilindro.estado_operativo == "APROBADO"
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "APROBADA"


async def test_cc_cierre_con_varios_cilindros(session_factory) -> None:
    user, clave, datos = await _ctx_cc(
        session_factory, estados=("APTO_LLENADO", "APTO_LLENADO")
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        c0, c1 = datos["cilindros"]

        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(c0, orden_id, "APROBADO"))
        assert resp.status_code == 201, resp.text
        async with session_factory() as session:
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "PENDIENTE_CALIDAD"

        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(c1, orden_id, "APROBADO"))
        assert resp.status_code == 201, resp.text
        async with session_factory() as session:
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "APROBADA"


async def test_cc_cierre_prioridad_rechazado(session_factory) -> None:
    """Un RECHAZADO pesa más que los APROBADO/APROBADO_OBSERVACIONES."""
    user, clave, datos = await _ctx_cc(
        session_factory, estados=("APTO_LLENADO", "APTO_LLENADO")
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        c0, c1 = datos["cilindros"]

        client.post(_RUTA_CC, headers=headers, json=_body_cc(c0, orden_id, "APROBADO_OBSERVACIONES"))
        client.post(_RUTA_CC, headers=headers, json=_body_cc(c1, orden_id, "RECHAZADO"))
        async with session_factory() as session:
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "RECHAZADA"


# ============================================================
# SEGREGACIÓN DE FUNCIONES (RN28)
# ============================================================


async def test_cc_separation_of_duties_403(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        cid = datos["cilindros"][0]

        # El usuario hizo la tarea de ejecución (TAREA_08) COMPLETADA del cilindro.
        async with session_factory() as session:
            tarea = (
                await session.execute(select(Tarea).where(Tarea.codigo == TAREA_LLENADO_EJECUTAR))
            ).scalar_one()
            usuario = await session.get(Usuario, user.id)
            session.add(
                TareaAsignada(
                    orden_id=uuid.UUID(orden_id),
                    tarea_id=tarea.id,
                    cilindro_id=cid,
                    responsable_id=usuario.empleado_id,
                    estado="COMPLETADA",
                )
            )
            await session.commit()

        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(cid, orden_id, "APROBADO"))
        assert resp.status_code == 403
        assert codigo_error(resp) == "SEPARATION_OF_DUTIES"

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cid)
            assert cilindro.estado_operativo == "PENDIENTE_CONTROL_CALIDAD"
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.estado == "PENDIENTE_CALIDAD"


# ============================================================
# VALIDACIONES
# ============================================================


async def test_cc_validaciones(session_factory) -> None:
    user, clave, datos = await _ctx_cc(
        session_factory, estados=("APTO_LLENADO", "APTO_LLENADO")
    )
    ajeno = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        # Orden en PENDIENTE (no PENDIENTE_CALIDAD) → 400.
        resp = client.post(
            _RUTA_OT,
            headers=headers,
            json=_body_orden(datos["area_id"], [datos["cilindros"][0]]),
        )
        assert resp.status_code == 201, resp.text
        orden_pend = resp.json()["id"]
        resp = client.post(
            _RUTA_CC, headers=headers, json=_body_cc(datos["cilindros"][0], orden_pend, "APROBADO")
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # Orden en calidad con cilindro que no pertenece → 400.
        orden_cal = _orden_en_calidad(client, headers, datos)
        c0, _ = datos["cilindros"]
        resp = client.post(
            _RUTA_CC, headers=headers, json=_body_cc(ajeno["cilindros"][0], orden_cal, "APROBADO")
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # Cilindro / orden desconocidos → 404.
        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(uuid.uuid4(), orden_cal, "APROBADO"))
        assert resp.status_code == 404
        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(c0, uuid.uuid4(), "APROBADO"))
        assert resp.status_code == 404

        # Repetir control sobre un cilindro ya controlado → 400.
        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(c0, orden_cal, "APROBADO"))
        assert resp.status_code == 201, resp.text
        resp = client.post(_RUTA_CC, headers=headers, json=_body_cc(c0, orden_cal, "RECHAZADO"))
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_cc_resultado_invalido_422(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        resp = client.post(
            _RUTA_CC,
            headers=headers,
            json=_body_cc(datos["cilindros"][0], orden_id, "PERFECTO"),
        )
        assert resp.status_code == 422


async def test_cc_checklist_invalido_422(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        resp = client.post(
            _RUTA_CC,
            headers=headers,
            json=_body_cc(datos["cilindros"][0], orden_id, "APROBADO", presion_ok="si"),
        )
        assert resp.status_code == 422


async def test_cc_desconocido_404(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(f"{_RUTA_CC}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


# ============================================================
# CONSULTA / APPEND-ONLY
# ============================================================


async def test_cc_listar_filtros(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        cid = datos["cilindros"][0]
        client.post(_RUTA_CC, headers=headers, json=_body_cc(cid, orden_id, "APROBADO"))

        resp = client.get(
            _RUTA_CC,
            headers=headers,
            params={
                "cilindro_id": str(cid),
                "orden_relacionada_id": orden_id,
                "usuario_id": str(user.id),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # Filtro por fecha: el control de hoy cae dentro de la ventana.
        ahora = datetime.now(UTC)
        resp = client.get(
            _RUTA_CC,
            headers=headers,
            params={"desde": (ahora - timedelta(hours=1)).isoformat()},
        )
        assert resp.json()["total"] >= 1
        resp = client.get(
            _RUTA_CC,
            headers=headers,
            params={
                "hasta": (ahora - timedelta(hours=1)).isoformat(),
                # Filtro acotado al cilindro de este test: la BD de prueba
                # persiste y con `hasta` global emparejaría los controles
                # acumulados de corridas anteriores (más de 1 h viejo).
                "cilindro_id": str(cid),
            },
        )
        assert resp.json()["total"] == 0


async def test_cc_append_only_405(session_factory) -> None:
    user, clave, datos = await _ctx_cc(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = _orden_en_calidad(client, headers, datos)
        resp = client.post(
            _RUTA_CC, headers=headers, json=_body_cc(datos["cilindros"][0], orden_id, "APROBADO")
        )
        assert resp.status_code == 201, resp.text
        control_id = resp.json()["id"]
        assert client.patch(f"{_RUTA_CC}/{control_id}", headers=headers, json={}).status_code == 405
        assert client.delete(f"{_RUTA_CC}/{control_id}", headers=headers).status_code == 405
