"""
Tests de la subetapa 5.1: recepción de cilindros.

Recepción (TAREA_04): `numero` del servidor (correlativo ``REC-<AÑO>-######``),
`usuario_responsable_id` = usuario autenticado, FKs → 404, estados
`COMPLETADA ⇄ ANULADA` (misma transición → 409, `Literal` inválido → 422),
`DELETE` de la cabecera no expuesto (405: se anula por estado). Detalles
anidados: cada cilindro recibido emite un `Movimiento` atómico (nace
`RECIBIDO`, o `PENDIENTE_INSPECCION` si `motivo_servicio = INSPECCION`),
un cilindro no se repite en la misma recepción (409), detalle de otra
recepción → 404, y el borrado del detalle no revierte el movimiento.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest
from factories import (
    TAREA_CILINDROS,
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
    Cilindro,
    Cliente,
    DetalleRecepcion,
    Movimiento,
    Permiso,
    Propietario,
    Tarea,
    TareaPermiso,
    TipoGas,
    Ubicacion,
)

_RUTA = "/api/v1/recepciones"
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]
_PATRON_NUMERO = re.compile(r"^REC-\d{4}-\d{6}$")


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _dominio(session_factory, *tareas: str):
    return await crear_cadena_rbac(session_factory, tareas=list(tareas), permisos=_PERMISOS)


# ============================================================
# HELPERS DE FIXTURES (directo en BD)
# ============================================================


async def _cliente_bd(session_factory) -> uuid.UUID:
    p = prefijo()
    async with session_factory() as session:
        cliente = Cliente(rut=f"1{p[:8]}", razon_social=f"Cliente {p[:6]}")
        session.add(cliente)
        await session.commit()
        return cliente.id


async def _propietario_bd(session_factory) -> uuid.UUID:
    p = prefijo()
    async with session_factory() as session:
        propietario = Propietario(tipo="AGAS", rut=f"2{p[:8]}", razon_social=f"Prop {p[:6]}")
        session.add(propietario)
        await session.commit()
        return propietario.id


async def _cilindro_bd(session_factory, *, estado_operativo: str = "REGISTRADO") -> uuid.UUID:
    p = prefijo()
    async with session_factory() as session:
        propietario = Propietario(tipo="AGAS", rut=f"6{p[:8]}", razon_social=f"Prop {p[:6]}")
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        ubicacion = Ubicacion(codigo=f"UB{p[:10]}", nombre=f"Bodega {p[:6]}", tipo="INTERNA")
        session.add_all([propietario, tipo_gas, ubicacion])
        await session.flush()
        cilindro = Cilindro(
            codigo_interno=f"CI{p[:10]}",
            numero_serie=f"NS{p[:10]}",
            codigo_qr=f"QR{p[:10]}",
            propietario_id=propietario.id,
            tipo_gas_id=tipo_gas.id,
            capacidad_kg=42,
            ubicacion_actual_id=ubicacion.id,
            estado_operativo=estado_operativo,
        )
        session.add(cilindro)
        await session.commit()
        return cilindro.id


def _body_recepcion(cliente_entrega_id, propietario_id, **extra) -> dict:
    body = {
        "cliente_entrega_id": str(cliente_entrega_id),
        "propietario_id": str(propietario_id),
        "motivo_servicio": "LLENADO",
    }
    body.update(extra)
    return body


async def _crear_recepcion_api(client, headers, cliente_entrega_id, propietario_id, **extra) -> dict:
    resp = client.post(
        _RUTA, headers=headers, json=_body_recepcion(cliente_entrega_id, propietario_id, **extra)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ============================================================
# GUARDS RBAC
# ============================================================


def test_recepcion_sin_autenticacion_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


async def test_recepcion_dominio_equivocado_403(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


async def test_recepcion_sin_permiso_403_y_menciona_permiso(session_factory) -> None:
    """Con la tarea pero sin PERM_02 en la matriz → 403 que menciona el permiso."""
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)

    async with session_factory() as session:
        tarea = (await session.execute(select(Tarea).where(Tarea.codigo == TAREA_RECEPCION))).scalar_one()
        permiso = (await session.execute(select(Permiso).where(Permiso.codigo == "PERM_02"))).scalar_one()
        claves = (tarea.id, permiso.id)
        fila = await session.get(TareaPermiso, claves)
        assert fila is not None
        fila.concedido = False
        await session.commit()

    try:
        with TestClient(app) as client:
            headers = _admin(client, user, clave)
            resp = client.post(
                _RUTA, headers=headers, json=_body_recepcion(cliente, propietario)
            )
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_02" in resp.json()["detail"]["message"]
    finally:
        async with session_factory() as session:
            fila = await session.get(TareaPermiso, claves)
            if fila is not None:
                fila.concedido = True
                await session.commit()


# ============================================================
# RECEPCIONES (cabecera)
# ============================================================


async def test_recepcion_crud_completo(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    solicitante = await _cliente_bd(session_factory)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_recepcion(
                cliente,
                propietario,
                cliente_solicita_id=str(solicitante),
                documento_referencia="GUIA-123",
                observaciones="Ingreso de prueba",
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert _PATRON_NUMERO.match(data["numero"])
        assert data["estado"] == "COMPLETADA"
        assert data["usuario_responsable_id"] == str(user.id)
        assert data["fecha_hora"] is not None
        rid = data["id"]

        assert client.get(f"{_RUTA}/{rid}", headers=headers).status_code == 200

        # Filtros: motivo, cliente_entrega, propietario, q e estado.
        resp = client.get(
            _RUTA,
            headers=headers,
            params={
                "motivo_servicio": "LLENADO",
                "cliente_entrega_id": str(cliente),
                "propietario_id": str(propietario),
                "estado": "COMPLETADA",
                "q": data["numero"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == rid

        # Actualización parcial.
        resp = client.patch(
            f"{_RUTA}/{rid}",
            headers=headers,
            json={"documento_referencia": "GUIA-999", "observaciones": "Actualizado"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["documento_referencia"] == "GUIA-999"


async def test_recepcion_numero_del_servidor_unico(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        primero = await _crear_recepcion_api(client, headers, cliente, propietario)
        segundo = await _crear_recepcion_api(client, headers, cliente, propietario)
        assert primero["numero"] != segundo["numero"]
        anio = datetime.now(UTC).year
        assert primero["numero"].startswith(f"REC-{anio}-")


@pytest.mark.parametrize(
    "campo",
    ["cliente_entrega_id", "propietario_id", "cliente_solicita_id"],
)
async def test_recepcion_fk_desconocidas_404(session_factory, campo: str) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    body = _body_recepcion(cliente, propietario, cliente_solicita_id=str(uuid.uuid4()))
    body[campo] = str(uuid.uuid4())
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=body)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_recepcion_campos_inmutables_no_editables(session_factory) -> None:
    """`cliente_entrega_id`, `propietario_id` y `motivo_servicio` no se editan."""
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        data = await _crear_recepcion_api(client, headers, cliente, propietario)
        rid = data["id"]

        resp = client.patch(
            f"{_RUTA}/{rid}", headers=headers, json={"motivo_servicio": "REPARACION"}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.patch(
            f"{_RUTA}/{rid}", headers=headers, json={"propietario_id": str(uuid.uuid4())}
        )
        assert resp.status_code == 400

        # Mezclado con un campo válido: solo se aplica lo válido.
        resp = client.patch(
            f"{_RUTA}/{rid}",
            headers=headers,
            json={"observaciones": "Ok", "motivo_servicio": "REPARACION"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["observaciones"] == "Ok"
        assert resp.json()["motivo_servicio"] == "LLENADO"


async def test_recepcion_null_significa_sin_cambio(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        data = await _crear_recepcion_api(client, headers, cliente, propietario)
        rid = data["id"]

        resp = client.patch(
            f"{_RUTA}/{rid}", headers=headers, json={"documento_referencia": None, "observaciones": None}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.patch(
            f"{_RUTA}/{rid}", headers=headers, json={"documento_referencia": "DOC-1", "observaciones": None}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["documento_referencia"] == "DOC-1"


async def test_recepcion_update_cliente_solicita(session_factory) -> None:
    """`cliente_solicita_id` es editable y se valida (404 si no existe)."""
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    solicitante = await _cliente_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        data = await _crear_recepcion_api(client, headers, cliente, propietario)
        rid = data["id"]

        resp = client.patch(
            f"{_RUTA}/{rid}", headers=headers, json={"cliente_solicita_id": str(solicitante)}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cliente_solicita_id"] == str(solicitante)

        resp = client.patch(
            f"{_RUTA}/{rid}", headers=headers, json={"cliente_solicita_id": str(uuid.uuid4())}
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_recepcion_estado_transiciones(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        data = await _crear_recepcion_api(client, headers, cliente, propietario)
        rid = data["id"]

        # Misma transición → 409 con allowed_states.
        resp = client.patch(f"{_RUTA}/{rid}/estado", headers=headers, json={"estado": "COMPLETADA"})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == ["ANULADA"]

        # Anular y reactivar (ambas direcciones).
        resp = client.patch(f"{_RUTA}/{rid}/estado", headers=headers, json={"estado": "ANULADA"})
        assert resp.status_code == 200
        assert resp.json()["estado"] == "ANULADA"
        resp = client.patch(f"{_RUTA}/{rid}/estado", headers=headers, json={"estado": "COMPLETADA"})
        assert resp.status_code == 200
        assert resp.json()["estado"] == "COMPLETADA"

        # Literal fuera de dominio → 422.
        resp = client.patch(f"{_RUTA}/{rid}/estado", headers=headers, json={"estado": "CANCELADA"})
        assert resp.status_code == 422


async def test_recepcion_router_sin_delete_405(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        data = await _crear_recepcion_api(client, headers, cliente, propietario)
        assert client.delete(f"{_RUTA}/{data['id']}", headers=headers).status_code == 405


async def test_recepcion_desconocida_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    desconocida = str(uuid.uuid4())
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.get(f"{_RUTA}/{desconocida}", headers=headers).status_code == 404
        resp = client.patch(f"{_RUTA}/{desconocida}", headers=headers, json={"observaciones": "x"})
        assert resp.status_code == 404
        resp = client.patch(
            f"{_RUTA}/{desconocida}/estado", headers=headers, json={"estado": "ANULADA"}
        )
        assert resp.status_code == 404


# ============================================================
# DETALLES
# ============================================================


async def test_detalle_recibir_emite_movimiento(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion = await _crear_recepcion_api(client, headers, cliente, propietario)

        resp = client.post(
            f"{_RUTA}/{recepcion['id']}/detalles",
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "estado_fisico": "BUENO",
                "nivel_llenado_pct": 80,
                "accesorios": {"valvula": "ok"},
            },
        )
        assert resp.status_code == 201, resp.text
        detalle = resp.json()
        assert detalle["estado_fisico"] == "BUENO"
        assert detalle["nivel_llenado_pct"] == 80
        assert detalle["accesorios"] == {"valvula": "ok"}
        detalle_id = detalle["id"]

        # El movimiento quedó registrado y el cilindro en RECIBIDO (atómico).
        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cilindro_id)
            assert cilindro.estado_operativo == "RECIBIDO"
            movimiento = (
                await session.execute(
                    select(Movimiento).where(Movimiento.cilindro_id == cilindro_id)
                )
            ).scalar_one()
            assert movimiento.estado_anterior == "REGISTRADO"
            assert movimiento.estado_nuevo == "RECIBIDO"
            assert movimiento.usuario_recibe_id == user.id
            assert recepcion["numero"] in movimiento.motivo

        # Listado, detalle y filtro por estado físico.
        resp = client.get(f"{_RUTA}/{recepcion['id']}/detalles", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert (
            client.get(
                f"{_RUTA}/{recepcion['id']}/detalles/{detalle_id}", headers=headers
            ).status_code
            == 200
        )
        resp = client.get(
            f"{_RUTA}/{recepcion['id']}/detalles",
            headers=headers,
            params={"estado_fisico": "MALO"},
        )
        assert resp.json()["total"] == 0


async def test_detalle_motivo_inspeccion_cambia_estado(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion = await _crear_recepcion_api(
            client, headers, cliente, propietario, motivo_servicio="INSPECCION"
        )
        resp = client.post(
            f"{_RUTA}/{recepcion['id']}/detalles",
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "estado_fisico": "REGULAR"},
        )
        assert resp.status_code == 201, resp.text

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cilindro_id)
            assert cilindro.estado_operativo == "PENDIENTE_INSPECCION"


async def test_detalle_cilindro_repetido_409(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion = await _crear_recepcion_api(client, headers, cliente, propietario)
        body = {"cilindro_id": str(cilindro_id), "estado_fisico": "BUENO"}
        assert client.post(f"{_RUTA}/{recepcion['id']}/detalles", headers=headers, json=body).status_code == 201
        resp = client.post(f"{_RUTA}/{recepcion['id']}/detalles", headers=headers, json=body)
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


async def test_detalle_en_recepcion_anulada_400(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion = await _crear_recepcion_api(client, headers, cliente, propietario)
        assert (
            client.patch(
                f"{_RUTA}/{recepcion['id']}/estado", headers=headers, json={"estado": "ANULADA"}
            ).status_code
            == 200
        )
        resp = client.post(
            f"{_RUTA}/{recepcion['id']}/detalles",
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "estado_fisico": "BUENO"},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "body",
    [
        {"estado_fisico": "BUENO", "nivel_llenado_pct": 101},
        {"estado_fisico": "BUENO", "nivel_llenado_pct": -1},
        {"estado_fisico": "DESTROZADO"},
    ],
)
async def test_detalle_validaciones_422(session_factory, body: dict) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion = await _crear_recepcion_api(client, headers, cliente, propietario)
        resp = client.post(
            f"{_RUTA}/{recepcion['id']}/detalles",
            headers=headers,
            json={"cilindro_id": str(cilindro_id), **body},
        )
        assert resp.status_code == 422


async def test_detalle_cilindro_desconocido_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion = await _crear_recepcion_api(client, headers, cliente, propietario)
        resp = client.post(
            f"{_RUTA}/{recepcion['id']}/detalles",
            headers=headers,
            json={"cilindro_id": str(uuid.uuid4()), "estado_fisico": "BUENO"},
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_detalle_acotado_a_su_recepcion(session_factory) -> None:
    """Detalle de otra recepción → 404 (GET y DELETE)."""
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion_a = await _crear_recepcion_api(client, headers, cliente, propietario)
        recepcion_b = await _crear_recepcion_api(client, headers, cliente, propietario)
        resp = client.post(
            f"{_RUTA}/{recepcion_a['id']}/detalles",
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "estado_fisico": "BUENO"},
        )
        detalle_id = resp.json()["id"]

        # El detalle pertenece a A: consultarlo/borrarlo desde B → 404.
        assert (
            client.get(
                f"{_RUTA}/{recepcion_b['id']}/detalles/{detalle_id}", headers=headers
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"{_RUTA}/{recepcion_b['id']}/detalles/{detalle_id}", headers=headers
            ).status_code
            == 404
        )

        # Recepción inexistente en el sub-recurso → 404.
        assert (
            client.get(f"{_RUTA}/{uuid.uuid4()}/detalles", headers=headers).status_code == 404
        )


async def test_detalle_eliminar_no_revierte_movimiento(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        recepcion = await _crear_recepcion_api(client, headers, cliente, propietario)
        resp = client.post(
            f"{_RUTA}/{recepcion['id']}/detalles",
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "estado_fisico": "BUENO"},
        )
        detalle_id = resp.json()["id"]

        assert (
            client.delete(
                f"{_RUTA}/{recepcion['id']}/detalles/{detalle_id}", headers=headers
            ).status_code
            == 204
        )
        assert (
            client.get(
                f"{_RUTA}/{recepcion['id']}/detalles/{detalle_id}", headers=headers
            ).status_code
            == 404
        )

        # El movimiento y el estado RECIBIDO persisten (traza inmutable).
        async with session_factory() as session:
            assert await session.get(DetalleRecepcion, uuid.UUID(detalle_id)) is None
            cilindro = await session.get(Cilindro, cilindro_id)
            assert cilindro.estado_operativo == "RECIBIDO"
            movimientos = (
                await session.execute(
                    select(Movimiento).where(Movimiento.cilindro_id == cilindro_id)
                )
            ).scalars().all()
            assert len(movimientos) == 1


async def test_recepcion_listado_incluye_numero(session_factory) -> None:
    """La cabecera recién creada aparece en el listado con su número."""
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        data = await _crear_recepcion_api(client, headers, cliente, propietario)
        resp = client.get(_RUTA, headers=headers, params={"q": data["numero"]})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["numero"] == data["numero"]


async def test_recepcion_motivo_invalido_422(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    cliente = await _cliente_bd(session_factory)
    propietario = await _propietario_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_recepcion(cliente, propietario, motivo_servicio="ROTURA"),
        )
        assert resp.status_code == 422


async def test_recepcion_lista_vacia_200(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 200
        assert "items" in resp.json()
