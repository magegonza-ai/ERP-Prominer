"""
Tests de la subetapa 5.3.a: órdenes de trabajo (cabecera, detalles y ciclo de vida).

`/ordenes-trabajo` sirve a llenado y reparación con **RBAC condicionado por
`tipo`**: crear/modificar y las transiciones exigen la tarea del tipo
(TAREA_07/08/09 para llenado; TAREA_10/12/13 para reparación) más el permiso
de la acción. El `numero` lo genera el servidor (`OTL`/`OTR-<AÑO>-######`), la
orden nace `PENDIENTE` con ≥ 1 cilindro elegible (`APTO_LLENADO` /
`APTO_REPARACION`) y cada transición que cambia el estado del cilindro emite
un `Movimiento` atómico (D31). El `DELETE` de cabecera no se expone (405).
"""

from __future__ import annotations

import uuid

import pytest
from factories import (
    TAREA_LLENADO_CERRAR,
    TAREA_LLENADO_CREAR,
    TAREA_LLENADO_EJECUTAR,
    TAREA_RECEPCION,
    TAREA_REPARACION_CERRAR,
    TAREA_REPARACION_CREAR,
    TAREA_REPARACION_EJECUTAR,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    crear_empleado,
    crear_tarea_unica,
    prefijo,
    token_de,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import (
    Area,
    Cilindro,
    DetalleOrden,
    Movimiento,
    OrdenTrabajo,
    Permiso,
    Propietario,
    Tarea,
    TareaAsignada,
    TareaPermiso,
    TipoGas,
    Ubicacion,
)

_RUTA = "/api/v1/ordenes-trabajo"
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_06", "PERM_07", "PERM_09", "PERM_10"]


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
            "propietario_id": propietario.id,
            "tipo_gas_id": tipo_gas.id,
            "ubicacion_id": ubicacion.id,
            "area_id": area.id,
            "cilindros": [c.id for c in cilindros],
        }


def _body(area_id, cilindros, *, tipo="LLENADO", **extra) -> dict:
    body = {
        "tipo": tipo,
        "area_responsable_id": str(area_id),
        "detalles": [{"cilindro_id": str(c)} for c in cilindros],
    }
    body.update(extra)
    return body


async def _crear(client, headers, datos, *, tipo="LLENADO", cilindros=None, **extra):
    if cilindros is None:
        cilindros = datos["cilindros"][:1]
    return client.post(
        _RUTA, headers=headers, json=_body(datos["area_id"], cilindros, tipo=tipo, **extra)
    )


# ============================================================
# GUARDS RBAC
# ============================================================


def test_orden_sin_autenticacion_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


async def test_orden_dominio_equivocado_403(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


async def test_orden_crear_sin_permiso_403(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)

    async with session_factory() as session:
        tarea = (await session.execute(select(Tarea).where(Tarea.codigo == TAREA_LLENADO_CREAR))).scalar_one()
        permiso = (await session.execute(select(Permiso).where(Permiso.codigo == "PERM_02"))).scalar_one()
        claves = (tarea.id, permiso.id)
        fila = await session.get(TareaPermiso, claves)
        assert fila is not None
        fila.concedido = False
        await session.commit()

    try:
        with TestClient(app) as client:
            headers = _admin(client, user, clave)
            resp = await _crear(client, headers, datos)
            assert resp.status_code == 403
            assert "PERM_02" in resp.json()["detail"]["message"]
    finally:
        async with session_factory() as session:
            fila = await session.get(TareaPermiso, claves)
            if fila is not None:
                fila.concedido = True
                await session.commit()


async def test_orden_crear_reparacion_sin_dominio_403(session_factory) -> None:
    """El RBAC depende del tipo: tener llenado no habilita una orden de reparación."""
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory, estados=("APTO_REPARACION",))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos, tipo="REPARACION")
        assert resp.status_code == 403
        assert "TAREA_10" in resp.json()["detail"]["message"]


async def test_orden_transicion_sin_dominio_403(session_factory) -> None:
    """Crear (TAREA_07) no habilita ejecutar (TAREA_08)."""
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        assert resp.status_code == 201, resp.text
        orden_id = resp.json()["id"]
        resp = client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "EN_PROCESO"})
        assert resp.status_code == 403
        assert "TAREA_08" in resp.json()["detail"]["message"]


# ============================================================
# ALTA
# ============================================================


@pytest.mark.parametrize(("tipo", "prefijo"), [("LLENADO", "OTL-"), ("REPARACION", "OTR-")])
async def test_orden_alta_numero_y_estado(session_factory, tipo: str, prefijo: str) -> None:
    estado_cilindro = "APTO_LLENADO" if tipo == "LLENADO" else "APTO_REPARACION"
    tareas = (TAREA_LLENADO_CREAR,) if tipo == "LLENADO" else (TAREA_REPARACION_CREAR,)
    user, clave = await _dominio(session_factory, *tareas)
    datos = await _base(session_factory, estados=(estado_cilindro,))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos, tipo=tipo)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["numero"].startswith(prefijo)
        assert data["tipo"] == tipo
        assert data["estado"] == "PENDIENTE"
        assert data["usuario_creador_id"] == str(user.id)
        assert data["prioridad"] == "NORMAL"

        async with session_factory() as session:
            detalles = (
                await session.execute(
                    select(DetalleOrden).where(DetalleOrden.orden_id == uuid.UUID(data["id"]))
                )
            ).scalars().all()
            assert len(detalles) == 1


async def test_orden_cilindro_no_elegible_400(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory, estados=("APTO_REPARACION",))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_orden_detalle_duplicado_409(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cid = datos["cilindros"][0]
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body(datos["area_id"], [cid, cid]),
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


async def test_orden_sin_detalles_422(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json={"tipo": "LLENADO", "area_responsable_id": str(datos["area_id"]), "detalles": []},
        )
        assert resp.status_code == 422


async def test_orden_area_y_cilindro_desconocidos_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body(uuid.uuid4(), datos["cilindros"]),
        )
        assert resp.status_code == 404

        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body(datos["area_id"], [uuid.uuid4()]),
        )
        assert resp.status_code == 404


async def test_orden_tipo_invalido_422(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body(datos["area_id"], datos["cilindros"], tipo="CALIDAD"),
        )
        assert resp.status_code == 422


# ============================================================
# CICLO DE VIDA + MOVIMIENTOS
# ============================================================


@pytest.mark.parametrize(
    ("tipo", "tareas", "secuencia"),
    [
        (
            "LLENADO",
            (TAREA_LLENADO_CREAR, TAREA_LLENADO_EJECUTAR, TAREA_LLENADO_CERRAR),
            [
                ("EN_PROCESO", "EN_PROCESO_LLENADO"),
                ("FINALIZADA", "FINALIZADO_LLENADO"),
                ("PENDIENTE_CALIDAD", "PENDIENTE_CONTROL_CALIDAD"),
            ],
        ),
        (
            "REPARACION",
            (TAREA_REPARACION_CREAR, TAREA_REPARACION_EJECUTAR, TAREA_REPARACION_CERRAR),
            [
                ("EN_PROCESO", "EN_REPARACION"),
                ("FINALIZADA", "REPARADO"),
                ("PENDIENTE_CALIDAD", "PENDIENTE_CONTROL_CALIDAD"),
            ],
        ),
    ],
)
async def test_orden_ciclo_de_vida(session_factory, tipo, tareas, secuencia) -> None:
    estado_inicial = "APTO_LLENADO" if tipo == "LLENADO" else "APTO_REPARACION"
    user, clave = await _dominio(session_factory, *tareas)
    datos = await _base(session_factory, estados=(estado_inicial, estado_inicial))
    cid = datos["cilindros"][0]
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos, tipo=tipo, cilindros=datos["cilindros"])
        assert resp.status_code == 201, resp.text
        orden_id = resp.json()["id"]

        for estado_orden, estado_cilindro in secuencia:
            resp = client.patch(
                f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": estado_orden}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["estado"] == estado_orden

            async with session_factory() as session:
                cilindro = await session.get(Cilindro, cid)
                assert cilindro.estado_operativo == estado_cilindro

        async with session_factory() as session:
            movimientos = (
                await session.execute(
                    select(Movimiento)
                    .where(Movimiento.cilindro_id == cid)
                    .order_by(Movimiento.fecha_hora)
                )
            ).scalars().all()
            assert [m.estado_nuevo for m in movimientos] == [s for _, s in secuencia]
            assert movimientos[0].estado_anterior == estado_inicial
            orden = await session.get(OrdenTrabajo, uuid.UUID(orden_id))
            assert orden.fecha_inicio is not None
            assert orden.fecha_termino_real is not None


async def test_orden_transicion_invalida_409(session_factory) -> None:
    user, clave = await _dominio(
        session_factory, TAREA_LLENADO_CREAR, TAREA_LLENADO_EJECUTAR, TAREA_LLENADO_CERRAR
    )
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]
        resp = client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "FINALIZADA"})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        extra = resp.json()["detail"]["extra"]
        assert extra["current_state"] == "PENDIENTE"
        assert "EN_PROCESO" in extra["allowed_states"]


async def test_orden_cancelar_sin_movimiento(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    cid = datos["cilindros"][0]
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]

        resp = client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "CANCELADA"})
        assert resp.status_code == 200
        assert resp.json()["estado"] == "CANCELADA"

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cid)
            assert cilindro.estado_operativo == "APTO_LLENADO"
            n = (
                await session.execute(select(Movimiento).where(Movimiento.cilindro_id == cid))
            ).scalars().all()
            assert n == []

        resp = client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "EN_PROCESO"})
        assert resp.status_code == 409


# ============================================================
# MODIFICAR CABECERA
# ============================================================


async def test_orden_patch_metadatos_y_validaciones(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]

        resp = client.patch(
            f"{_RUTA}/{orden_id}",
            headers=headers,
            json={"prioridad": "URGENTE", "observaciones": "Priorizar"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["prioridad"] == "URGENTE"

        # `null` = sin cambio → nada que actualizar.
        resp = client.patch(f"{_RUTA}/{orden_id}", headers=headers, json={"prioridad": None})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_orden_patch_solo_pendiente_400(session_factory) -> None:
    user, clave = await _dominio(
        session_factory, TAREA_LLENADO_CREAR, TAREA_LLENADO_EJECUTAR
    )
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]
        client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "EN_PROCESO"})

        resp = client.patch(
            f"{_RUTA}/{orden_id}", headers=headers, json={"prioridad": "EXPRESS"}
        )
        assert resp.status_code == 400


# ============================================================
# DETALLES
# ============================================================


async def test_orden_agregar_y_quitar_detalle(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory, estados=("APTO_LLENADO", "APTO_LLENADO"))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos, cilindros=[datos["cilindros"][0]])
        orden_id = resp.json()["id"]

        # Agregar el segundo cilindro.
        resp = client.post(
            f"{_RUTA}/{orden_id}/detalles",
            headers=headers,
            json={"cilindro_id": str(datos["cilindros"][1])},
        )
        assert resp.status_code == 201, resp.text

        # Repetir → 409.
        resp = client.post(
            f"{_RUTA}/{orden_id}/detalles",
            headers=headers,
            json={"cilindro_id": str(datos["cilindros"][1])},
        )
        assert resp.status_code == 409

        # Listar y quitar.
        resp = client.get(f"{_RUTA}/{orden_id}/detalles", headers=headers)
        assert resp.json()["total"] == 2
        detalle_id = resp.json()["items"][1]["id"]
        assert client.delete(f"{_RUTA}/{orden_id}/detalles/{detalle_id}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA}/{orden_id}/detalles", headers=headers).json()["total"] == 1


async def test_orden_detalles_bloqueados_no_pendiente_400(session_factory) -> None:
    user, clave = await _dominio(
        session_factory, TAREA_LLENADO_CREAR, TAREA_LLENADO_EJECUTAR
    )
    datos = await _base(session_factory, estados=("APTO_LLENADO", "APTO_LLENADO"))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos, cilindros=[datos["cilindros"][0]])
        orden_id = resp.json()["id"]
        client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "EN_PROCESO"})

        resp = client.post(
            f"{_RUTA}/{orden_id}/detalles",
            headers=headers,
            json={"cilindro_id": str(datos["cilindros"][1])},
        )
        assert resp.status_code == 400


async def test_orden_detalle_ejecucion(session_factory) -> None:
    user, clave = await _dominio(
        session_factory, TAREA_LLENADO_CREAR, TAREA_LLENADO_EJECUTAR
    )
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]
        detalle_id = client.get(f"{_RUTA}/{orden_id}/detalles", headers=headers).json()["items"][0]["id"]

        # En PENDIENTE no se registran resultados.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/detalles/{detalle_id}",
            headers=headers,
            json={"peso_final_kg": 45.5},
        )
        assert resp.status_code == 400

        client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "EN_PROCESO"})
        resp = client.patch(
            f"{_RUTA}/{orden_id}/detalles/{detalle_id}",
            headers=headers,
            json={"peso_inicial_kg": 40.0, "peso_final_kg": 45.5, "presion_bar": 200.0, "lote_gas": "L-1"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["peso_final_kg"] == 45.5
        assert data["lote_gas"] == "L-1"


async def test_orden_detalle_de_otra_orden_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory, estados=("APTO_LLENADO", "APTO_LLENADO"))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp1 = await _crear(client, headers, datos, cilindros=[datos["cilindros"][0]])
        resp2 = await _crear(client, headers, datos, cilindros=[datos["cilindros"][1]])
        orden2_id = resp2.json()["id"]
        detalle1_id = client.get(f"{_RUTA}/{resp1.json()['id']}/detalles", headers=headers).json()["items"][0]["id"]

        resp = client.get(f"{_RUTA}/{orden2_id}/detalles/{detalle1_id}", headers=headers)
        assert resp.status_code == 404


# ============================================================
# CONSULTA / LISTADO / METODO NO EXPUESTO
# ============================================================


async def test_orden_listar_filtros(session_factory) -> None:
    user, clave = await _dominio(
        session_factory,
        TAREA_LLENADO_CREAR,
        TAREA_REPARACION_CREAR,
    )
    datos = await _base(session_factory, estados=("APTO_LLENADO", "APTO_REPARACION"))
    area = str(datos["area_id"])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(
            client,
            headers,
            datos,
            tipo="LLENADO",
            cilindros=[datos["cilindros"][0]],
            usuario_asignado_id=str(user.id),
            prioridad="URGENTE",
        )
        numero = resp.json()["numero"]
        await _crear(client, headers, datos, tipo="REPARACION", cilindros=[datos["cilindros"][1]])

        def total(**params) -> int:
            return client.get(_RUTA, headers=headers, params={**params, "area_responsable_id": area}).json()["total"]

        # El área es única de este test → aísla del resto de la BD persistente.
        assert total(tipo="LLENADO") == 1
        assert total(prioridad="URGENTE") == 1
        assert total(usuario_asignado_id=str(user.id)) == 1
        assert total(estado="PENDIENTE") == 2
        assert client.get(_RUTA, headers=headers, params={"q": numero}).json()["total"] == 1
        assert total(desde="2000-01-01T00:00:00Z") == 2
        assert total(hasta="2000-01-01T00:00:00Z") == 0


async def test_orden_fks_opcionales_y_detalle_tipo_gas(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory, estados=("APTO_LLENADO", "APTO_LLENADO"))
    tg = str(datos["tipo_gas_id"])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json={
                "tipo": "LLENADO",
                "area_responsable_id": str(datos["area_id"]),
                "usuario_asignado_id": str(user.id),
                "tipo_gas_id": tg,
                "detalles": [{"cilindro_id": str(datos["cilindros"][0]), "tipo_gas_id": tg}],
            },
        )
        assert resp.status_code == 201, resp.text
        orden_id = resp.json()["id"]

        # Detalle con tipo_gas_id (valida la FK opcional).
        resp = client.post(
            f"{_RUTA}/{orden_id}/detalles",
            headers=headers,
            json={"cilindro_id": str(datos["cilindros"][1]), "tipo_gas_id": tg},
        )
        assert resp.status_code == 201, resp.text

        # PATCH de cabecera con las FK opcionales válidas.
        resp = client.patch(
            f"{_RUTA}/{orden_id}",
            headers=headers,
            json={
                "area_responsable_id": str(datos["area_id"]),
                "usuario_asignado_id": str(user.id),
                "tipo_gas_id": tg,
                "diagnostico": "Revisar válvula",
            },
        )
        assert resp.status_code == 200, resp.text


async def test_orden_detalle_ejecucion_sin_campos_400(session_factory) -> None:
    user, clave = await _dominio(
        session_factory, TAREA_LLENADO_CREAR, TAREA_LLENADO_EJECUTAR
    )
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]
        detalle_id = client.get(f"{_RUTA}/{orden_id}/detalles", headers=headers).json()["items"][0]["id"]
        client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "EN_PROCESO"})
        resp = client.patch(
            f"{_RUTA}/{orden_id}/detalles/{detalle_id}", headers=headers, json={}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_orden_quitar_detalle_no_pendiente_400(session_factory) -> None:
    user, clave = await _dominio(
        session_factory, TAREA_LLENADO_CREAR, TAREA_LLENADO_EJECUTAR
    )
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]
        detalle_id = client.get(f"{_RUTA}/{orden_id}/detalles", headers=headers).json()["items"][0]["id"]
        client.patch(f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "EN_PROCESO"})

        resp = client.delete(f"{_RUTA}/{orden_id}/detalles/{detalle_id}", headers=headers)
        assert resp.status_code == 400


async def test_orden_desconocida_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_orden_delete_cabecera_405(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = await _crear(client, headers, datos)
        orden_id = resp.json()["id"]
        assert client.delete(f"{_RUTA}/{orden_id}", headers=headers).status_code == 405


# ============================================================
# TAREAS ASIGNADAS (5.3.b)
# ============================================================


async def _tarea_id(session_factory, codigo: str) -> uuid.UUID:
    async with session_factory() as session:
        return (await session.execute(select(Tarea).where(Tarea.codigo == codigo))).scalar_one().id


async def _ctx_tareas(session_factory, *extra_tareas: str):
    """Usuario que crea órdenes y asigna (TAREA_07+28+08) + tarea/empleado listos."""
    user, clave = await _dominio(
        session_factory,
        TAREA_LLENADO_CREAR,
        TAREA_USUARIOS,
        TAREA_LLENADO_EJECUTAR,
        *extra_tareas,
    )
    datos = await _base(session_factory)
    tarea_id = await _tarea_id(session_factory, TAREA_LLENADO_EJECUTAR)
    empleado, _area = await crear_empleado(session_factory)
    return user, clave, datos, tarea_id, empleado


def _body_tarea(tarea_id, responsable_id, **extra) -> dict:
    body = {"tarea_id": str(tarea_id), "responsable_id": str(responsable_id)}
    body.update(extra)
    return body


async def _asignar(client, headers, orden_id, body):
    return client.post(f"{_RUTA}/{orden_id}/tareas", headers=headers, json=body)


async def test_tarea_asignar_listar_y_consultar(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]

        resp = await _asignar(client, headers, orden_id, _body_tarea(tarea_id, empleado.id))
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["estado"] == "ASIGNADA"
        assert data["responsable_id"] == str(empleado.id)
        assert data["tarea_id"] == str(tarea_id)
        assert data["orden_id"] == orden_id
        assert data["fecha_asignacion"] is not None

        listado = client.get(f"{_RUTA}/{orden_id}/tareas", headers=headers)
        assert listado.status_code == 200
        assert listado.json()["total"] == 1
        ta_id = data["id"]
        detalle = client.get(f"{_RUTA}/{orden_id}/tareas/{ta_id}", headers=headers)
        assert detalle.status_code == 200
        assert detalle.json()["id"] == ta_id


async def test_tarea_asignar_con_cilindro_de_la_orden(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]
        cilindro_id = datos["cilindros"][0]
        resp = await _asignar(
            client,
            headers,
            orden_id,
            _body_tarea(tarea_id, empleado.id, cilindro_id=str(cilindro_id)),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["cilindro_id"] == str(cilindro_id)


async def test_tarea_asignar_validaciones(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    otra = await _base(session_factory)
    tarea_inactiva = await crear_tarea_unica(session_factory)
    empleado_inactivo, _area = await crear_empleado(session_factory, estado="INACTIVO")
    async with session_factory() as session:
        tarea = await session.get(Tarea, tarea_inactiva.id)
        tarea.estado = "INACTIVA"
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]

        # Orden desconocida.
        resp = await _asignar(client, headers, uuid.uuid4(), _body_tarea(tarea_id, empleado.id))
        assert resp.status_code == 404
        # Tarea desconocida.
        resp = await _asignar(client, headers, orden_id, _body_tarea(uuid.uuid4(), empleado.id))
        assert resp.status_code == 404
        # Empleado desconocido.
        resp = await _asignar(client, headers, orden_id, _body_tarea(tarea_id, uuid.uuid4()))
        assert resp.status_code == 404
        # Cilindro que no pertenece a la orden.
        resp = await _asignar(
            client,
            headers,
            orden_id,
            _body_tarea(tarea_id, empleado.id, cilindro_id=str(otra["cilindros"][0])),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        # Tarea no ACTIVA.
        resp = await _asignar(
            client, headers, orden_id, _body_tarea(tarea_inactiva.id, empleado.id)
        )
        assert resp.status_code == 400
        # Empleado no ACTIVO.
        resp = await _asignar(
            client, headers, orden_id, _body_tarea(tarea_id, empleado_inactivo.id)
        )
        assert resp.status_code == 400
        # Orden CANCELADA.
        client.patch(
            f"{_RUTA}/{orden_id}/estado", headers=headers, json={"estado": "CANCELADA"}
        )
        resp = await _asignar(client, headers, orden_id, _body_tarea(tarea_id, empleado.id))
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_tarea_patch_transiciones(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]
        ta_id = (
            await _asignar(client, headers, orden_id, _body_tarea(tarea_id, empleado.id))
        ).json()["id"]

        # Misma transición (ASIGNADA → ASIGNADA) → 409 con allowed_states.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}", headers=headers, json={"estado": "ASIGNADA"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == ["EN_PROCESO", "CANCELADA"]

        # ASIGNADA → EN_PROCESO fija fecha_inicio.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}",
            headers=headers,
            json={"estado": "EN_PROCESO"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["fecha_inicio"] is not None

        # EN_PROCESO → COMPLETADA fija fecha_termino.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}",
            headers=headers,
            json={"estado": "COMPLETADA", "resultado": "Llenado conforme"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["fecha_termino"] is not None

        # Estado terminal → 409.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}",
            headers=headers,
            json={"estado": "EN_PROCESO"},
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"


async def test_tarea_patch_sin_campos_y_datos_ejecucion(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]
        ta_id = (
            await _asignar(client, headers, orden_id, _body_tarea(tarea_id, empleado.id))
        ).json()["id"]

        # Sin campos → 400.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}", headers=headers, json={}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # `null` = sin cambio; se actualizan prioridad/observaciones/evidencias.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}",
            headers=headers,
            json={
                "estado": None,
                "prioridad": "URGENTE",
                "observaciones": "Revisar válvula",
                "evidencias": {"foto": "a.jpg"},
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["estado"] == "ASIGNADA"
        assert data["prioridad"] == "URGENTE"
        assert data["observaciones"] == "Revisar válvula"
        assert data["evidencias"] == {"foto": "a.jpg"}


async def test_tarea_guards_por_dominio(session_factory) -> None:
    admin, clave_admin, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    user07, clave07 = await _dominio(session_factory, TAREA_LLENADO_CREAR)
    otro, _area = await crear_empleado(session_factory)

    with TestClient(app) as client:
        ha = _admin(client, admin, clave_admin)
        orden_id = (await _crear(client, ha, datos)).json()["id"]
        ta_id = (
            await _asignar(client, ha, orden_id, _body_tarea(tarea_id, empleado.id))
        ).json()["id"]

        hb = _admin(client, user07, clave07)
        # Asignar exige TAREA_28 (no la tiene) → 403.
        resp = await _asignar(client, hb, orden_id, _body_tarea(tarea_id, empleado.id))
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"
        # Modificar exige TAREA_28/08/12 (no las tiene) → 403.
        resp = client.patch(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}",
            headers=hb,
            json={"estado": "EN_PROCESO"},
        )
        assert resp.status_code == 403
        # Reasignar exige TAREA_28 → 403.
        resp = client.post(
            f"{_RUTA}/{orden_id}/tareas/{ta_id}/reasignar",
            headers=hb,
            json={"nuevo_responsable_id": str(otro.id)},
        )
        assert resp.status_code == 403


async def test_tarea_reasignar_con_traza(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    nuevo, _area = await crear_empleado(session_factory)
    inactivo, _area2 = await crear_empleado(session_factory, estado="INACTIVO")
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]
        original = (
            await _asignar(client, headers, orden_id, _body_tarea(tarea_id, empleado.id))
        ).json()

        resp = client.post(
            f"{_RUTA}/{orden_id}/tareas/{original['id']}/reasignar",
            headers=headers,
            json={"nuevo_responsable_id": str(nuevo.id), "motivo": "Vacaciones"},
        )
        assert resp.status_code == 201, resp.text
        nueva = resp.json()
        assert nueva["responsable_id"] == str(nuevo.id)
        assert nueva["estado"] == "ASIGNADA"
        assert nueva["reasignada_desde_id"] == original["id"]
        assert nueva["usuario_reasigno_id"] == str(user.id)
        assert nueva["fecha_reasignacion"] is not None
        assert nueva["motivo_reasignacion"] == "Vacaciones"

        # La original queda REASIGNADA.
        detalle = client.get(
            f"{_RUTA}/{orden_id}/tareas/{original['id']}", headers=headers
        ).json()
        assert detalle["estado"] == "REASIGNADA"
        async with session_factory() as session:
            orig = await session.get(TareaAsignada, uuid.UUID(original["id"]))
            reemplazo = await session.get(TareaAsignada, uuid.UUID(nueva["id"]))
            assert orig.estado == "REASIGNADA"
            assert reemplazo.reasignada_desde_id == orig.id

        # Reasignar la original (terminal) → 400.
        resp = client.post(
            f"{_RUTA}/{orden_id}/tareas/{original['id']}/reasignar",
            headers=headers,
            json={"nuevo_responsable_id": str(empleado.id)},
        )
        assert resp.status_code == 400
        # Mismo responsable → 400.
        resp = client.post(
            f"{_RUTA}/{orden_id}/tareas/{nueva['id']}/reasignar",
            headers=headers,
            json={"nuevo_responsable_id": str(nuevo.id)},
        )
        assert resp.status_code == 400
        # Nuevo responsable inactivo → 400.
        resp = client.post(
            f"{_RUTA}/{orden_id}/tareas/{nueva['id']}/reasignar",
            headers=headers,
            json={"nuevo_responsable_id": str(inactivo.id)},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def _set_matriz(session_factory, codigo_permiso: str, concedido: bool) -> bool:
    """Concede/revoca un permiso en TAREA_28; devuelve el valor anterior."""
    async with session_factory() as session:
        tarea = (
            await session.execute(select(Tarea).where(Tarea.codigo == TAREA_USUARIOS))
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


async def test_tarea_reasignar_sin_permiso_403(session_factory) -> None:
    admin, clave_admin, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    # Usuario con SOLO TAREA_28: así revocar su PERM_10 no se compensa con
    # otra tarea que lo tenga concedido (la matriz es global por tarea).
    solo28, clave28 = await _dominio(session_factory, TAREA_USUARIOS)
    nuevo, _area = await crear_empleado(session_factory)

    anterior = await _set_matriz(session_factory, "PERM_10", False)
    try:
        with TestClient(app) as client:
            ha = _admin(client, admin, clave_admin)
            orden_id = (await _crear(client, ha, datos)).json()["id"]
            ta_id = (
                await _asignar(client, ha, orden_id, _body_tarea(tarea_id, empleado.id))
            ).json()["id"]

            hb = _admin(client, solo28, clave28)
            resp = client.post(
                f"{_RUTA}/{orden_id}/tareas/{ta_id}/reasignar",
                headers=hb,
                json={"nuevo_responsable_id": str(nuevo.id)},
            )
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
    finally:
        await _set_matriz(session_factory, "PERM_10", bool(anterior))


async def test_tarea_asignar_sin_permiso_09_403(session_factory) -> None:
    admin, clave_admin, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    solo28, clave28 = await _dominio(session_factory, TAREA_USUARIOS)

    anterior = await _set_matriz(session_factory, "PERM_09", False)
    try:
        with TestClient(app) as client:
            ha = _admin(client, admin, clave_admin)
            orden_id = (await _crear(client, ha, datos)).json()["id"]

            hb = _admin(client, solo28, clave28)
            resp = await _asignar(client, hb, orden_id, _body_tarea(tarea_id, empleado.id))
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
    finally:
        await _set_matriz(session_factory, "PERM_09", bool(anterior))


async def test_tarea_listar_filtros(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    otro, _area = await crear_empleado(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]
        await _asignar(client, headers, orden_id, _body_tarea(tarea_id, empleado.id))
        await _asignar(client, headers, orden_id, _body_tarea(tarea_id, otro.id))

        base = f"{_RUTA}/{orden_id}/tareas"
        assert client.get(base, headers=headers).json()["total"] == 2
        assert (
            client.get(base, headers=headers, params={"estado": "ASIGNADA"}).json()["total"] == 2
        )
        assert (
            client.get(base, headers=headers, params={"estado": "COMPLETADA"}).json()["total"]
            == 0
        )
        assert (
            client.get(
                base, headers=headers, params={"responsable_id": str(empleado.id)}
            ).json()["total"]
            == 1
        )
        assert (
            client.get(base, headers=headers, params={"tarea_id": str(tarea_id)}).json()["total"]
            == 2
        )


async def test_tarea_metodos_no_expuestos_y_404(session_factory) -> None:
    user, clave, datos, tarea_id, empleado = await _ctx_tareas(session_factory)
    datos2 = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        orden_id = (await _crear(client, headers, datos)).json()["id"]
        ta_id = (
            await _asignar(client, headers, orden_id, _body_tarea(tarea_id, empleado.id))
        ).json()["id"]

        # Sin DELETE (405).
        assert (
            client.delete(f"{_RUTA}/{orden_id}/tareas/{ta_id}", headers=headers).status_code == 405
        )
        # Tarea asignada desconocida → 404.
        resp = client.get(f"{_RUTA}/{orden_id}/tareas/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"
        # Tarea asignada de otra orden → 404.
        orden2 = (await _crear(client, headers, datos2)).json()["id"]
        resp = client.get(f"{_RUTA}/{orden2}/tareas/{ta_id}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"
