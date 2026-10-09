"""
Tests de la subetapa 5.5: despacho y entregas de cilindros.

`/entregas` (TAREA_17 «Preparar entregas» / TAREA_18 «Entregar cilindros»):
cabecera con cilindros anidados (`DetalleEntrega`, cantidad fija 1 y montos
calculados) y ciclo de vida BORRADOR → PENDIENTE → CONFIRMADA → ENTREGADA
(+ CANCELADA terminal). La lectura exige TAREA_17 ∨ TAREA_18 + PERM_01;
crear y editar usan TAREA_17 (PERM_02/PERM_03); la confirmación PERM_06
(TAREA_17); entregar exige **TAREA_18** + PERM_06 (D36) y anular usa
TAREA_17 + PERM_03 (la matriz sembrada de TAREA_17/18 no otorga PERM_07).

Cada cilindro debe estar despachable (RN13: `APROBADO`/`LISTO_PARA_ENTREGAR`),
pertenecer al propietario de la entrega y no estar en otra entrega activa.
Al pasar a `ENTREGADA` se emite un `Movimiento` por cilindro en la misma
transacción (D31): ``<estado actual> → ENTREGADO`` sin cambio de ubicación.
"""

from __future__ import annotations

from factories import (
    TAREA_ENTREGAR,
    TAREA_PREPARAR_ENTREGAS,
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
    Movimiento,
    Permiso,
    Propietario,
    Tarea,
    TareaPermiso,
    TipoGas,
    Ubicacion,
)

_RUTA = "/api/v1/entregas"
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_04", "PERM_05", "PERM_06", "PERM_07"]
# UUID bien formado que nunca existirá en BD (para forzar 404).
_UUID_INEXISTENTE = "00000000-0000-0000-0000-000000000000"


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _dominio(session_factory, *tareas: str):
    return await crear_cadena_rbac(session_factory, tareas=list(tareas), permisos=_PERMISOS)


# ============================================================
# HELPERS DE FIXTURES (directo en BD)
# ============================================================


async def _base(
    session_factory,
    *,
    estados=("LISTO_PARA_ENTREGAR",),
    cliente_estado="ACTIVO",
) -> dict:
    """Crea cliente, propietario, tipo de gas, ubicación y N cilindros."""
    p = prefijo()
    async with session_factory() as session:
        cliente = Cliente(
            rut=f"7{p[:8]}", razon_social=f"Cliente {p[:6]}", estado=cliente_estado
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
        }


async def _ctx(session_factory, *, estados=("LISTO_PARA_ENTREGAR",), tareas=None, **base_extra) -> tuple:
    """Usuario del dominio de entregas + datos base."""
    tareas = tareas or (TAREA_PREPARAR_ENTREGAS, TAREA_ENTREGAR)
    user, clave = await _dominio(session_factory, *tareas)
    datos = await _base(session_factory, estados=estados, **base_extra)
    return user, clave, datos


def _body_entrega(cliente_id, propietario_id, cilindros, **extra) -> dict:
    body = {
        "cliente_recibe_id": str(cliente_id),
        "propietario_id": str(propietario_id),
        "receptor_nombre": "Receptor Test",
        "receptor_relacion": "CHOFER",
        "detalles": [{"cilindro_id": str(c)} for c in cilindros],
    }
    body.update(extra)
    return body


def _crear_entrega(client: TestClient, headers: dict, datos: dict, cilindros=None) -> str:
    cilindros = cilindros or datos["cilindros"]
    resp = client.post(
        _RUTA, headers=headers, json=_body_entrega(datos["cliente_id"], datos["propietario_id"], cilindros)
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


def test_entrega_sin_autenticacion_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


async def test_entrega_dominio_equivocado_403(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


async def test_entrega_solo_preparar_no_puede_entregar_403(session_factory) -> None:
    """Entregar (→ ENTREGADA) exige TAREA_18 aunque se tenga TAREA_17."""
    user, clave, datos = await _ctx(session_factory, tareas=(TAREA_PREPARAR_ENTREGAS,))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)
        for estado in ("PENDIENTE", "CONFIRMADA"):
            resp = client.patch(
                f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": estado}
            )
            assert resp.status_code == 200, resp.text
        resp = client.patch(
            f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": "ENTREGADA"}
        )
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"
        assert "TAREA_18" in resp.json()["detail"]["message"]


# ============================================================
# ALTA DE ENTREGA (BORRADOR)
# ============================================================


async def test_entrega_crear_borrador_completa(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("LISTO_PARA_ENTREGAR",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_entrega(
                datos["cliente_id"],
                datos["propietario_id"],
                datos["cilindros"],
                observaciones="Entregar en bodega norte",
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["estado"] == "BORRADOR"
        assert data["numero"].startswith("ENT-")
        assert data["usuario_responsable_id"] == str(user.id)
        assert data["fecha_hora"] is not None
        assert data["cliente_recibe"]["id"] == str(datos["cliente_id"])
        assert data["cliente_recibe"]["razon_social"].startswith("Cliente ")
        assert data["propietario"]["id"] == str(datos["propietario_id"])
        assert data["receptor_nombre"] == "Receptor Test"
        assert data["receptor_relacion"] == "CHOFER"
        assert data["observaciones"] == "Entregar en bodega norte"
        assert len(data["detalles"]) == 2
        for detalle in data["detalles"]:
            assert detalle["cantidad"] == 1
            assert detalle["cilindro"]["estado_operativo"] == "LISTO_PARA_ENTREGAR"
            assert detalle["cilindro"]["tipo_gas"]["nombre"].startswith("Gas ")
            assert detalle["subtotal"] == 0
            assert detalle["total"] == 0


async def test_entrega_numeracion_secuencial(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("LISTO_PARA_ENTREGAR",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        p1 = _crear_entrega(client, headers, datos, cilindros=[datos["cilindros"][0]])
        p2 = _crear_entrega(client, headers, datos, cilindros=[datos["cilindros"][1]])
        r1 = client.get(f"{_RUTA}/{p1}", headers=headers)
        r2 = client.get(f"{_RUTA}/{p2}", headers=headers)
        n1 = r1.json()["numero"]
        n2 = r2.json()["numero"]
        assert n1.startswith("ENT-")
        assert n2.startswith("ENT-")
        assert n1 != n2


async def test_entrega_calcula_totales(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("LISTO_PARA_ENTREGAR",))
    cuerpo = _body_entrega(
        datos["cliente_id"],
        datos["propietario_id"],
        datos["cilindros"],
    )
    cuerpo["detalles"][0].update(
        precio_unitario=100, descuento_pct=10, tasa_impuesto_pct=19
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 201, resp.text
        detalle = resp.json()["detalles"][0]
        assert detalle["subtotal"] == 90        # 100 - 10% de descuento
        assert detalle["impuesto_monto"] == 17.1  # 19% de 90
        assert detalle["total"] == 107.1


async def test_entrega_cliente_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_entrega(_UUID_INEXISTENTE, datos["propietario_id"], datos["cilindros"])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_entrega_propietario_inexistente_404(session_factory) -> None:
    """Propietario inexistente → 404 en el alta y en el reemplazo."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_entrega(datos["cliente_id"], _UUID_INEXISTENTE, datos["cilindros"]),
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        entrega_id = _crear_entrega(client, headers, datos)
        resp = client.put(
            f"{_RUTA}/{entrega_id}",
            headers=headers,
            json=_body_entrega(datos["cliente_id"], _UUID_INEXISTENTE, datos["cilindros"]),
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_entrega_cliente_inactivo_400(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, cliente_estado="INACTIVO")
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_entrega(datos["cliente_id"], datos["propietario_id"], datos["cilindros"]),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_entrega_cilindro_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_entrega(datos["cliente_id"], datos["propietario_id"], [_UUID_INEXISTENTE])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_entrega_cilindro_otro_propietario_400(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    ajeno = await _base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_entrega(datos["cliente_id"], datos["propietario_id"], [ajeno["cilindros"][0]]),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_entrega_cilindro_no_despachable_422(session_factory) -> None:
    """RN13: un cilindro REGISTRADO (ni APROBADO ni LISTO_PARA_ENTREGAR) no se despacha."""
    user, clave, datos = await _ctx(session_factory, estados=("REGISTRADO",))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_entrega(datos["cliente_id"], datos["propietario_id"], datos["cilindros"]),
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "BUSINESS_RULE_ERROR"


async def test_entrega_cilindro_duplicado_409(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("LISTO_PARA_ENTREGAR",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_entrega(
                datos["cliente_id"], datos["propietario_id"], [datos["cilindros"][0], datos["cilindros"][0]]
            ),
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


async def test_entrega_cilindro_en_otra_entrega_409(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("LISTO_PARA_ENTREGAR",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        _crear_entrega(client, headers, datos, cilindros=[datos["cilindros"][0]])
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_entrega(datos["cliente_id"], datos["propietario_id"], datos["cilindros"]),
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


async def test_entrega_sin_detalles_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_entrega(datos["cliente_id"], datos["propietario_id"], [])
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


async def test_entrega_receptor_obligatorio_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    cuerpo = _body_entrega(datos["cliente_id"], datos["propietario_id"], datos["cilindros"])
    del cuerpo["receptor_nombre"]
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


# ============================================================
# EDICIÓN (solo en BORRADOR, replace-all)
# ============================================================


async def test_entrega_reemplazo_borrador_200(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory, estados=("LISTO_PARA_ENTREGAR",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos, cilindros=[datos["cilindros"][0]])

        cuerpo = _body_entrega(
            datos["cliente_id"],
            datos["propietario_id"],
            [datos["cilindros"][1]],
            receptor_nombre="Nuevo Receptor",
            observaciones="Cambio de planificación",
        )
        resp = client.put(f"{_RUTA}/{entrega_id}", headers=headers, json=cuerpo)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["detalles"]) == 1
        assert data["detalles"][0]["cilindro_id"] == str(datos["cilindros"][1])
        assert data["receptor_nombre"] == "Nuevo Receptor"
        assert data["observaciones"] == "Cambio de planificación"


async def test_entrega_reemplazo_fuera_de_borrador_400(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)
        resp = client.patch(
            f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": "PENDIENTE"}
        )
        assert resp.status_code == 200, resp.text

        resp = client.put(
            f"{_RUTA}/{entrega_id}",
            headers=headers,
            json=_body_entrega(datos["cliente_id"], datos["propietario_id"], datos["cilindros"]),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        assert "BORRADOR" in resp.json()["detail"]["message"]


# ============================================================
# CICLO DE VIDA
# ============================================================


async def test_entrega_pendiente_y_confirmada_ok(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)
        for estado in ("PENDIENTE", "CONFIRMADA"):
            resp = client.patch(
                f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": estado}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["estado"] == estado


async def test_entrega_pendiente_sin_permiso_403(session_factory) -> None:
    """→ PENDIENTE exige TAREA_17 + PERM_03 (modificar)."""
    user, clave, datos = await _ctx(session_factory, tareas=(TAREA_PREPARAR_ENTREGAS,))
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)
        anterior = await _set_matriz(session_factory, TAREA_PREPARAR_ENTREGAS, "PERM_03", False)
        try:
            resp = client.patch(
                f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": "PENDIENTE"}
            )
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_03" in resp.json()["detail"]["message"]
        finally:
            await _set_matriz(session_factory, TAREA_PREPARAR_ENTREGAS, "PERM_03", bool(anterior))


async def test_entrega_ciclo_hasta_entregada_movimiento(session_factory) -> None:
    """Al ENTREGAR cada cilindro emite un Movimiento y pasa a ENTREGADO (D31)."""
    user, clave, datos = await _ctx(session_factory, estados=("LISTO_PARA_ENTREGAR",) * 2)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)

        for estado in ("PENDIENTE", "CONFIRMADA"):
            resp = client.patch(
                f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": estado}
            )
            assert resp.status_code == 200, resp.text

        resp = client.patch(
            f"{_RUTA}/{entrega_id}/estado",
            headers=headers,
            json={
                "estado": "ENTREGADA",
                "receptor_nombre": "Sra. Pérez",
                "receptor_rut": "7.123.456-7",
                "receptor_relacion": "PROPIETARIO",
                "firma_confirmacion_url": "https://cdn.example.com/firma/abc.png",
                "firma_tipo": "DIGITAL",
                "observaciones": "Firmado digitalmente por la receptora",
                "motivo": "Entrega verificada en terreno",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["estado"] == "ENTREGADA"
        assert data["receptor_nombre"] == "Sra. Pérez"
        assert data["firma_tipo"] == "DIGITAL"
        assert data["firma_confirmacion_url"].startswith("https://")
        assert data["observaciones"] == "Firmado digitalmente por la receptora"

        async with session_factory() as session:
            for cid in datos["cilindros"]:
                cilindro = await session.get(Cilindro, cid)
                assert cilindro.estado_operativo == "ENTREGADO"
                movimientos = (
                    await session.execute(
                        select(Movimiento).where(Movimiento.cilindro_id == cid)
                    )
                ).scalars().all()
                assert len(movimientos) == 1
                mov = movimientos[0]
                assert mov.estado_anterior == "LISTO_PARA_ENTREGAR"
                assert mov.estado_nuevo == "ENTREGADO"
                assert mov.usuario_entrega_id == user.id
                assert mov.motivo == "Entrega verificada en terreno"
                assert mov.ubicacion_origen_id == cilindro.ubicacion_actual_id
                assert mov.ubicacion_destino_id == cilindro.ubicacion_actual_id


async def test_entrega_cancelada_libera_cilindros(session_factory) -> None:
    """CANCELADA no cambia el cilindro y libera sus cilindros para otra entrega."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)
        resp = client.patch(
            f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": "CANCELADA"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["estado"] == "CANCELADA"

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindros"][0])
            assert cilindro.estado_operativo == "LISTO_PARA_ENTREGAR"

        # El mismo cilindro vuelve a ser elegible para una nueva entrega.
        segunda = _crear_entrega(client, headers, datos)
        assert segunda


async def test_entrega_transicion_invalida_409(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)

        # BORRADOR → CONFIRMADA salta PENDIENTE.
        resp = client.patch(
            f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": "CONFIRMADA"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"

        # Misma transición BORRADOR → BORRADOR también es inválida.
        resp = client.patch(
            f"{_RUTA}/{entrega_id}/estado", headers=headers, json={"estado": "BORRADOR"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"


async def test_entrega_estado_literal_invalido_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)
        resp = client.patch(
            f"{_RUTA}/{entrega_id}/estado",
            headers=headers,
            json={"estado": "EXCEPCION_DOC"},
        )
        assert resp.status_code == 422


# ============================================================
# CONSULTA
# ============================================================


async def test_entrega_detalle_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_PREPARAR_ENTREGAS, TAREA_ENTREGAR)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(f"{_RUTA}/{_UUID_INEXISTENTE}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_entrega_listar_filtros(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        entrega_id = _crear_entrega(client, headers, datos)
        numero = client.get(f"{_RUTA}/{entrega_id}", headers=headers).json()["numero"]

        # Filtro por número (q): exactamente 1.
        resp = client.get(_RUTA, headers=headers, params={"q": numero})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == entrega_id

        # Filtro por estado BORRADOR: al menos contiene la nueva entrega.
        resp = client.get(_RUTA, headers=headers, params={"estado": "BORRADOR"})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # Filtro por cliente y propietario.
        resp = client.get(
            _RUTA,
            headers=headers,
            params={"cliente_recibe_id": datos["cliente_id"], "propietario_id": datos["propietario_id"]},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # Filtro por rango de fechas: una ventana anterior a todo no coincide
        # (fecha de la entrega = ahora > ventana).
        resp = client.get(
            _RUTA,
            headers=headers,
            params={"desde": "2000-01-01T00:00:00Z", "hasta": "2001-01-01T00:00:00Z"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
