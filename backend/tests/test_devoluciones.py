"""
Tests de la subetapa 5.6: devoluciones de cilindros.

`/devoluciones` (TAREA_19 «Registrar devoluciones», matriz sembrada
`[0,1,2,7]` = PERM_01/02/03/07): cabecera con cilindros anidados
(`DevolucionDetalle`) y ciclo de vida REGISTRADA → ANULADA (terminal).

Cada cilindro debe estar `ENTREGADO` (retorna a AGAS), no repetirse y no
figurar en otra devolución activa. Al registrar se emite un `Movimiento` por
cilindro en la misma transacción (D31): ``ENTREGADO → RECIBIDO`` con
`usuario_recibe_id` (y cambio de ubicación si se indica `ubicacion_destino_id`).
Anular exige PERM_07 y **no** revierte la traza (el cilindro ya regresó).
"""

from __future__ import annotations

from factories import (
    TAREA_ENTREGAR,
    TAREA_PREPARAR_ENTREGAS,
    TAREA_REGISTRAR_DEVOLUCIONES,
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
    Devolucion,
    DevolucionDetalle,
    Movimiento,
    Permiso,
    Propietario,
    Tarea,
    TareaPermiso,
    TipoGas,
    Ubicacion,
)

_RUTA = "/api/v1/devoluciones"
# Matriz diseñada de TAREA_19: consultar/crear/modificar/anular (sin PERM_06).
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]
# UUID bien formado que nunca existirá en BD (para forzar 404).
_UUID_INEXISTENTE = "00000000-0000-0000-0000-000000000000"


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _dominio(session_factory, *tareas: str):
    return await crear_cadena_rbac(session_factory, tareas=list(tareas), permisos=_PERMISOS)


# ============================================================
# HELPERS DE FIXTURES (directo en BD)
# ============================================================


async def _base(session_factory, *, estados=("ENTREGADO",)) -> dict:
    """Crea cliente, propietario, tipo de gas, ubicación y N cilindros."""
    p = prefijo()
    async with session_factory() as session:
        cliente = Cliente(
            rut=f"7{p[:8]}", razon_social=f"Cliente {p[:6]}", estado="ACTIVO"
        )
        propietario = Propietario(tipo="AGAS", rut=f"2{p[:8]}", razon_social=f"Prop {p[:6]}")
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        ubicacion = Ubicacion(codigo=f"UB{p[:10]}", nombre=f"Bodega {p[:6]}", tipo="INTERNA")
        session.add_all([cliente, propietario, tipo_gas, ubicacion])
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
            "cliente_id": cliente.id,
            "propietario_id": propietario.id,
            "cilindros": [c.id for c in cilindros],
            "ubicacion_id": ubicacion.id,
        }


async def _ctx(session_factory, *, estados=("ENTREGADO",), tareas=None) -> tuple:
    """Usuario del dominio de devoluciones + datos base."""
    tareas = tareas or (TAREA_REGISTRAR_DEVOLUCIONES,)
    user, clave = await _dominio(session_factory, *tareas)
    datos = await _base(session_factory, estados=estados)
    return user, clave, datos


def _body_devolucion(cliente_id, cilindros, **extra) -> dict:
    body = {
        "cliente_devuelve_id": str(cliente_id),
        "motivo": "DEVOLUCION_CLIENTE",
        "detalles": [{"cilindro_id": str(c), "estado_fisico": "BUENO"} for c in cilindros],
    }
    body.update(extra)
    return body


def _crear_devolucion(client: TestClient, headers: dict, datos: dict, cilindros=None) -> str:
    cilindros = cilindros or datos["cilindros"]
    resp = client.post(
        _RUTA, headers=headers, json=_body_devolucion(datos["cliente_id"], cilindros)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


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


def test_devolucion_sin_autenticacion_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


async def test_devolucion_dominio_equivocado_403(session_factory) -> None:
    """TAREA_17/18 (entregas) no abre devoluciones."""
    user, clave = await _dominio(session_factory, TAREA_PREPARAR_ENTREGAS, TAREA_ENTREGAR)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


# ============================================================
# ALTA DE DEVOLUCIÓN (REGISTRADA)
# ============================================================


async def test_devolucion_crear_registrada_completa(session_factory) -> None:
    """Alta con 2 cilindros: numero del servidor, movimiento atómico a RECIBIDO."""
    user, clave, datos = await _ctx(session_factory, estados=("ENTREGADO",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_devolucion(
                datos["cliente_id"],
                datos["cilindros"],
                motivo="DANO_EN_TRANSITO",
                documento_referencia="GUIA-123",
                observaciones="Cilindros con golpes al llegar",
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["estado"] == "REGISTRADA"
        assert data["numero"].startswith("DEV-")
        assert data["usuario_responsable_id"] == str(user.id)
        assert data["fecha_hora"] is not None
        assert data["cliente_devuelve"]["id"] == str(datos["cliente_id"])
        assert data["cliente_devuelve"]["razon_social"].startswith("Cliente ")
        assert data["motivo"] == "DANO_EN_TRANSITO"
        assert data["documento_referencia"] == "GUIA-123"
        assert data["observaciones"] == "Cilindros con golpes al llegar"
        assert len(data["detalles"]) == 2
        for detalle in data["detalles"]:
            assert detalle["estado_fisico"] == "BUENO"
            assert detalle["cilindro"]["estado_operativo"] == "RECIBIDO"

        async with session_factory() as session:
            for cid in datos["cilindros"]:
                cilindro = await session.get(Cilindro, cid)
                assert cilindro.estado_operativo == "RECIBIDO"
                movimientos = (
                    await session.execute(
                        select(Movimiento).where(Movimiento.cilindro_id == cid)
                    )
                ).scalars().all()
                assert len(movimientos) == 1
                mov = movimientos[0]
                assert mov.estado_anterior == "ENTREGADO"
                assert mov.estado_nuevo == "RECIBIDO"
                assert mov.usuario_recibe_id == user.id
                assert mov.usuario_entrega_id is None
                assert mov.motivo == f"Devolución {data['numero']}"
                assert mov.ubicacion_origen_id == cilindro.ubicacion_actual_id
                assert mov.ubicacion_destino_id == cilindro.ubicacion_actual_id


async def test_devolucion_numeracion_secuencial(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("ENTREGADO",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        d1 = _crear_devolucion(client, headers, datos, cilindros=[datos["cilindros"][0]])
        d2 = _crear_devolucion(client, headers, datos, cilindros=[datos["cilindros"][1]])
        n1 = client.get(f"{_RUTA}/{d1}", headers=headers).json()["numero"]
        n2 = client.get(f"{_RUTA}/{d2}", headers=headers).json()["numero"]
        assert n1.startswith("DEV-")
        assert n2.startswith("DEV-")
        assert n1 != n2


async def test_devolucion_cliente_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_devolucion(_UUID_INEXISTENTE, datos["cilindros"])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_devolucion_cliente_inactivo_400(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_REGISTRAR_DEVOLUCIONES)
    p = prefijo()
    async with session_factory() as session:
        cliente = Cliente(rut=f"7{p[:8]}", razon_social=f"Cliente {p[:6]}", estado="INACTIVO")
        session.add(cliente)
        await session.flush()
        await session.commit()
        cliente_id = cliente.id
    datos = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_devolucion(cliente_id, datos["cilindros"]),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_devolucion_entrega_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_devolucion(datos["cliente_id"], datos["cilindros"], entrega_id=_UUID_INEXISTENTE)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_devolucion_ubicacion_destino_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_devolucion(
        datos["cliente_id"], datos["cilindros"], ubicacion_destino_id=_UUID_INEXISTENTE
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_devolucion_cilindro_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_devolucion(datos["cliente_id"], [_UUID_INEXISTENTE])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_devolucion_cilindro_no_entregado_400(session_factory) -> None:
    """Un cilindro RECIBIDO (no ENTREGADO) no se puede devolver."""
    user, clave, datos = await _ctx(session_factory, estados=("RECIBIDO",))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_devolucion(datos["cliente_id"], datos["cilindros"]),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        assert "ENTREGADO" in resp.json()["detail"]["message"]


async def test_devolucion_cilindro_duplicado_409(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("ENTREGADO",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_devolucion(
                datos["cliente_id"], [datos["cilindros"][0], datos["cilindros"][0]]
            ),
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


async def test_devolucion_cilindro_en_otra_devolucion_409(session_factory) -> None:
    """Un cilindro ligado a otra devolución activa no se puede devolver de nuevo.

    La ocupación se siembra directo en BD: una devolución registrada por API
    ya deja el cilindro en `RECIBIDO`, así que el caso de colisión real lo
    simula un registro vigente cuyo cilindro aún está `ENTREGADO`.
    """
    user, clave, datos = await _ctx(session_factory, estados=("ENTREGADO",) * 2)
    p = prefijo()
    async with session_factory() as session:
        devolucion = Devolucion(
            numero=f"DEV-{p[:12]}",
            estado="REGISTRADA",
            usuario_responsable_id=user.id,
            cliente_devuelve_id=datos["cliente_id"],
            motivo="OTRO",
        )
        session.add(devolucion)
        await session.flush()
        session.add(
            DevolucionDetalle(
                devolucion_id=devolucion.id,
                cilindro_id=datos["cilindros"][0],
                estado_fisico="BUENO",
            )
        )
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_devolucion(datos["cliente_id"], datos["cilindros"]),
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


async def test_devolucion_sin_detalles_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_devolucion(datos["cliente_id"], [])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


async def test_devolucion_motivo_literal_invalido_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_devolucion(datos["cliente_id"], datos["cilindros"], motivo="OTRO_MOTIVO")
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


async def test_devolucion_estado_fisico_literal_invalido_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_devolucion(datos["cliente_id"], datos["cilindros"])
    cuerpo["detalles"][0]["estado_fisico"] = "DESCONOCIDO"
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


async def test_devolucion_destino_cambia_ubicacion(session_factory) -> None:
    """Con `ubicacion_destino_id`, el movimiento y el cilindro cambian de ubicación."""
    user, clave, datos = await _ctx(session_factory, estados=("ENTREGADO",))
    p = prefijo()
    async with session_factory() as session:
        destino = Ubicacion(codigo=f"UB{p[:10]}", nombre=f"Reingreso {p[:6]}", tipo="INTERNA")
        session.add(destino)
        await session.flush()
        await session.commit()
        destino_id = destino.id

    cuerpo = _body_devolucion(
        datos["cliente_id"], datos["cilindros"], ubicacion_destino_id=str(destino_id)
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 201, resp.text
        assert resp.json()["ubicacion_destino"]["id"] == str(destino_id)

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindros"][0])
            assert cilindro.ubicacion_actual_id == destino_id
            mov = (
                await session.execute(
                    select(Movimiento).where(Movimiento.cilindro_id == cilindro.id)
                )
            ).scalar_one()
            assert mov.ubicacion_origen_id == datos["ubicacion_id"]
            assert mov.ubicacion_destino_id == destino_id


# ============================================================
# EDICIÓN (solo en REGISTRADA, campos descriptivos)
# ============================================================


async def test_devolucion_patch_descriptivo_200(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)

        resp = client.patch(
            f"{_RUTA}/{devolucion_id}",
            headers=headers,
            json={"motivo": "ERROR_ENTREGA", "observaciones": "Se corrigió el registro"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["motivo"] == "ERROR_ENTREGA"
        assert data["observaciones"] == "Se corrigió el registro"


async def test_devolucion_patch_sin_campos_400(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)

        resp = client.patch(f"{_RUTA}/{devolucion_id}", headers=headers, json={})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_devolucion_patch_fuera_de_registrada_400(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)

        resp = client.patch(
            f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "ANULADA"}
        )
        assert resp.status_code == 200, resp.text

        resp = client.patch(
            f"{_RUTA}/{devolucion_id}", headers=headers, json={"observaciones": "tarde"}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        assert "REGISTRADA" in resp.json()["detail"]["message"]


# ============================================================
# CICLO DE VIDA (REGISTRADA → ANULADA)
# ============================================================


async def test_devolucion_anular_ok_sin_revertir_traza(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)

        resp = client.patch(
            f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "ANULADA"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["estado"] == "ANULADA"

        # La anulación no revierte la traza: el cilindro sigue RECIBIDO y el
        # Movimiento permanece (D31, trazabilidad append-only).
        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindros"][0])
            assert cilindro.estado_operativo == "RECIBIDO"
            movimientos = (
                await session.execute(
                    select(Movimiento).where(Movimiento.cilindro_id == cilindro.id)
                )
            ).scalars().all()
            assert len(movimientos) == 1
            assert movimientos[0].estado_nuevo == "RECIBIDO"


async def test_devolucion_anular_sin_perm_07_403(session_factory) -> None:
    """→ ANULADA exige TAREA_19 + PERM_07 (anular), no el PERM_03 de modificar."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)

        anterior = await _set_matriz(session_factory, TAREA_REGISTRAR_DEVOLUCIONES, "PERM_07", False)
        try:
            resp = client.patch(
                f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "ANULADA"}
            )
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_07" in resp.json()["detail"]["message"]
        finally:
            await _set_matriz(session_factory, TAREA_REGISTRAR_DEVOLUCIONES, "PERM_07", bool(anterior))


async def test_devolucion_anular_misma_estado_409(session_factory) -> None:
    """REGISTRADA → REGISTRADA y ANULADA → ANULADA son transiciones inválidas."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)

        resp = client.patch(
            f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "REGISTRADA"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"

        # REGISTRADA → ANULADA sí es válida (PERM_07).
        resp = client.patch(
            f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "ANULADA"}
        )
        assert resp.status_code == 200, resp.text

        # ANULADA es terminal: ANULADA → ANULADA vuelve a ser inválida.
        resp = client.patch(
            f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "ANULADA"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"

        # ANULADA → REGISTRADA tampoco está permitida (terminal, 409).
        resp = client.patch(
            f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "REGISTRADA"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"


async def test_devolucion_estado_literal_invalido_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)
        resp = client.patch(
            f"{_RUTA}/{devolucion_id}/estado", headers=headers, json={"estado": "PENDIENTE"}
        )
        assert resp.status_code == 422


# ============================================================
# CONSULTA
# ============================================================


async def test_devolucion_detalle_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_REGISTRAR_DEVOLUCIONES)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(f"{_RUTA}/{_UUID_INEXISTENTE}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_devolucion_listar_filtros(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)
        numero = client.get(f"{_RUTA}/{devolucion_id}", headers=headers).json()["numero"]

        # Filtro por número (q): exactamente 1.
        resp = client.get(_RUTA, headers=headers, params={"q": numero})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == devolucion_id

        # Filtro por estado REGISTRADA: al menos contiene la nueva devolución.
        resp = client.get(_RUTA, headers=headers, params={"estado": "REGISTRADA"})
        assert resp.json()["total"] >= 1

        # Filtro por cliente y motivo.
        resp = client.get(
            _RUTA,
            headers=headers,
            params={"cliente_devuelve_id": datos["cliente_id"], "motivo": "DEVOLUCION_CLIENTE"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # Rango de fechas anterior a todo no coincide con ninguna devolución.
        resp = client.get(
            _RUTA,
            headers=headers,
            params={"desde": "2000-01-01T00:00:00Z", "hasta": "2001-01-01T00:00:00Z"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


async def test_devolucion_delete_405(session_factory) -> None:
    """El DELETE de la cabecera no se expone: una devolución se anula por estado."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        devolucion_id = _crear_devolucion(client, headers, datos)
        resp = client.delete(f"{_RUTA}/{devolucion_id}", headers=headers)
        assert resp.status_code == 405
