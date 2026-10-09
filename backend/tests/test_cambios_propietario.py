"""
Tests de la subetapa 5.7: cambios de propietario de cilindros.

`/cambios-propietario` (TAREA_20 «Autorizar cambio de propietario», matriz
sembrada `[0,3,4]` = PERM_01 leer / PERM_04 aprobar / PERM_05 rechazar):
historial **append-only** de traspasos de propiedad. `POST` (PERM_04) crea el
registro y **aplica el traspaso al cilindro en la misma transacción**
(cilindro.propietario_id = propietario_nuevo_id); `propietario_anterior_id`,
`fecha` y `usuario_autoriza_id` los deriva el servidor. No hay edición ni
anulación (PATCH/DELETE → 405) y no emite `Movimiento` (D31 no aplica: no
cambia ubicación ni estado operativo; la traza es el propio historial).
"""

from __future__ import annotations

from factories import (
    TAREA_AUTORIZAR_CAMBIO_PROPIETARIO,
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
    CambioPropietario,
    Cilindro,
    Cliente,
    Permiso,
    Propietario,
    Tarea,
    TareaPermiso,
    TipoGas,
    Ubicacion,
)

_RUTA = "/api/v1/cambios-propietario"
# Matriz diseñada de TAREA_20: leer/autorizar (PERM_01/PERM_04); PERM_05 se
# deja sembrado sin endpoint (precedente PERM_08 «Exportar» de la 4.1).
_PERMISOS = ["PERM_01", "PERM_04"]
_UUID_INEXISTENTE = "00000000-0000-0000-0000-000000000000"


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _dominio(session_factory, *tareas: str):
    return await crear_cadena_rbac(session_factory, tareas=list(tareas), permisos=_PERMISOS)


# ============================================================
# HELPERS DE FIXTURES (directo en BD)
# ============================================================


async def _base(session_factory) -> dict:
    """Cliente, propietario inicial (AGAS), propietario destino, gas, ubicación y cilindro."""
    p = prefijo()
    async with session_factory() as session:
        cliente = Cliente(rut=f"7{p[:8]}", razon_social=f"Cliente {p[:6]}", estado="ACTIVO")
        propietario_a = Propietario(tipo="AGAS", rut=f"2{p[:8]}", razon_social=f"AGAS {p[:6]}")
        propietario_b = Propietario(
            tipo="EMPRESA_EXTERNA", rut=f"3{p[:8]}", razon_social=f"Externa {p[:6]}"
        )
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        ubicacion = Ubicacion(codigo=f"UB{p[:10]}", nombre=f"Bodega {p[:6]}", tipo="INTERNA")
        session.add_all([cliente, propietario_a, propietario_b, tipo_gas, ubicacion])
        await session.flush()

        cilindro = Cilindro(
            codigo_interno=f"CI{p[:8]}",
            numero_serie=f"NS{p[:8]}",
            codigo_qr=f"QR{p[:8]}",
            propietario_id=propietario_a.id,
            tipo_gas_id=tipo_gas.id,
            capacidad_kg=42,
            ubicacion_actual_id=ubicacion.id,
            estado_operativo="RECIBIDO",
        )
        session.add(cilindro)
        await session.flush()
        await session.commit()
        return {
            "cliente_id": cliente.id,
            "propietario_a_id": propietario_a.id,
            "propietario_b_id": propietario_b.id,
            "cilindro_id": cilindro.id,
            "ubicacion_id": ubicacion.id,
        }


async def _ctx(session_factory, tareas=None) -> tuple:
    tareas = tareas or (TAREA_AUTORIZAR_CAMBIO_PROPIETARIO,)
    user, clave = await _dominio(session_factory, *tareas)
    datos = await _base(session_factory)
    return user, clave, datos


def _body_cambio(datos, propietario_nuevo_id=None, **extra) -> dict:
    body = {
        "cilindro_id": str(datos["cilindro_id"]),
        "propietario_nuevo_id": str(propietario_nuevo_id or datos["propietario_b_id"]),
        "motivo": "Traspaso documentado",
    }
    body.update(extra)
    return body


def _crear_cambio(client: TestClient, headers: dict, datos: dict, **extra) -> str:
    resp = client.post(_RUTA, headers=headers, json=_body_cambio(datos, **extra))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_matriz(session_factory, codigo_tarea: str, codigo_permiso: str, concedido: bool) -> bool:
    async with session_factory() as session:
        tarea = (await session.execute(select(Tarea).where(Tarea.codigo == codigo_tarea))).scalar_one()
        permiso = (await session.execute(select(Permiso).where(Permiso.codigo == codigo_permiso))).scalar_one()
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


def test_cambio_sin_autenticacion_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


async def test_cambio_dominio_equivocado_403(session_factory) -> None:
    """TAREA_19 (devoluciones) no abre `/cambios-propietario`."""
    user, clave = await _dominio(session_factory, TAREA_REGISTRAR_DEVOLUCIONES)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


# ============================================================
# ALTA (= AUTORIZACIÓN, PERM_04)
# ============================================================


async def test_cambio_crear_autorizado_completo(session_factory) -> None:
    """POST crea el traspaso y lo aplica al cilindro en la misma transacción."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_cambio(datos, documento_respaldo_url="s3://respaldos/traspaso-1.pdf", observaciones="OK"),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["cilindro_id"] == str(datos["cilindro_id"])
        assert data["propietario_anterior_id"] == str(datos["propietario_a_id"])
        assert data["propietario_nuevo_id"] == str(datos["propietario_b_id"])
        assert data["usuario_autoriza_id"] == str(user.id)
        assert data["fecha"] is not None
        assert data["motivo"] == "Traspaso documentado"
        assert data["documento_respaldo_url"] == "s3://respaldos/traspaso-1.pdf"
        assert data["observaciones"] == "OK"
        # El cilindro de la respuesta ya refleja el nuevo propietario.
        assert data["cilindro"]["propietario_id"] == str(datos["propietario_b_id"])
        assert data["propietario_anterior"]["id"] == str(datos["propietario_a_id"])
        assert data["propietario_anterior"]["razon_social"].startswith("AGAS ")
        assert data["propietario_nuevo"]["id"] == str(datos["propietario_b_id"])
        assert data["propietario_nuevo"]["razon_social"].startswith("Externa ")
        assert data["usuario_autoriza"]["username"] == user.username

        # Efecto atómico en BD: propietario_id del cilindro + registro del historial.
        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindro_id"])
            assert cilindro.propietario_id == datos["propietario_b_id"]
            cambios = (
                await session.execute(
                    select(CambioPropietario).where(CambioPropietario.cilindro_id == cilindro.id)
                )
            ).scalars().all()
            assert len(cambios) == 1
            c = cambios[0]
            assert c.propietario_anterior_id == datos["propietario_a_id"]
            assert c.propietario_nuevo_id == datos["propietario_b_id"]
            assert c.usuario_autoriza_id == user.id
            # No emite Movimiento (D31 no aplica: no cambia ubicación ni estado).
            assert cilindro.estado_operativo == "RECIBIDO"


async def test_cambio_historial_secuencial(session_factory) -> None:
    """Dos traspasos consecutivos del mismo cilindro (revert) dejan el rastro completo."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        _crear_cambio(client, headers, datos)  # A → B
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_cambio(datos, propietario_nuevo_id=datos["propietario_a_id"]),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["propietario_anterior_id"] == str(datos["propietario_b_id"])
        assert data["propietario_nuevo_id"] == str(datos["propietario_a_id"])

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindro_id"])
            assert cilindro.propietario_id == datos["propietario_a_id"]
            cambios = (
                await session.execute(
                    select(CambioPropietario).where(CambioPropietario.cilindro_id == cilindro.id)
                )
            ).scalars().all()
            assert len(cambios) == 2


async def test_cambio_cilindro_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cuerpo = _body_cambio(datos)
        cuerpo["cilindro_id"] = _UUID_INEXISTENTE
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_cambio_propietario_nuevo_inexistente_404(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cuerpo = _body_cambio(datos, propietario_nuevo_id=_UUID_INEXISTENTE)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_cambio_propietario_inactivo_400(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    p = prefijo()
    async with session_factory() as session:
        inactivo = Propietario(
            tipo="EMPRESA_EXTERNA", rut=f"9{p[:8]}", razon_social=f"Inactivo {p[:6]}", estado="INACTIVO"
        )
        session.add(inactivo)
        await session.flush()
        await session.commit()
        inactivo_id = inactivo.id

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_cambio(datos, propietario_nuevo_id=inactivo_id),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        assert "ACTIVO" in resp.json()["detail"]["message"]


async def test_cambio_no_op_400(session_factory) -> None:
    """Traspasar al mismo propietario actual es un no-op (400)."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body_cambio(datos, propietario_nuevo_id=datos["propietario_a_id"]),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        assert "ya pertenece" in resp.json()["detail"]["message"]


async def test_cambio_crear_sin_perm_04_403(session_factory) -> None:
    """El POST es autorizar: exige TAREA_20 + PERM_04 (no basta PERM_01)."""
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        anterior = await _set_matriz(session_factory, TAREA_AUTORIZAR_CAMBIO_PROPIETARIO, "PERM_04", False)
        try:
            resp = client.post(_RUTA, headers=headers, json=_body_cambio(datos))
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_04" in resp.json()["detail"]["message"]
        finally:
            await _set_matriz(session_factory, TAREA_AUTORIZAR_CAMBIO_PROPIETARIO, "PERM_04", bool(anterior))


async def test_cambio_motivo_vacio_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cuerpo = _body_cambio(datos, motivo="")
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


async def test_cambio_motivo_omitido_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cuerpo = _body_cambio(datos)
        del cuerpo["motivo"]
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


async def test_cambio_documento_url_muy_larga_422(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cuerpo = _body_cambio(datos, documento_respaldo_url="x" * 501)
        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 422


# ============================================================
# CONSULTA
# ============================================================


async def test_cambio_listar_filtros(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cambio_id = _crear_cambio(client, headers, datos)

        # Por cilindro: exactamente 1.
        resp = client.get(_RUTA, headers=headers, params={"cilindro_id": datos["cilindro_id"]})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == cambio_id

        # Por propietario anterior y por nuevo.
        resp = client.get(_RUTA, headers=headers, params={"propietario_anterior_id": datos["propietario_a_id"]})
        assert resp.json()["total"] == 1
        resp = client.get(_RUTA, headers=headers, params={"propietario_nuevo_id": datos["propietario_b_id"]})
        assert resp.json()["total"] == 1

        # Por autorizador.
        resp = client.get(_RUTA, headers=headers, params={"usuario_autoriza_id": user.id})
        assert resp.json()["total"] == 1

        # Rango de fechas anterior a todo: 0 resultados.
        resp = client.get(
            _RUTA,
            headers=headers,
            params={"desde": "2000-01-01T00:00:00Z", "hasta": "2001-01-01T00:00:00Z"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


async def test_cambio_detalle_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_AUTORIZAR_CAMBIO_PROPIETARIO)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(f"{_RUTA}/{_UUID_INEXISTENTE}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


# ============================================================
# HISTORIAL FIRME (PATCH/DELETE → 405)
# ============================================================


async def test_cambio_patch_405(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cambio_id = _crear_cambio(client, headers, datos)
        resp = client.patch(f"{_RUTA}/{cambio_id}", headers=headers, json={"motivo": "otro"})
        assert resp.status_code == 405


async def test_cambio_delete_405(session_factory) -> None:
    user, clave, datos = await _ctx(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cambio_id = _crear_cambio(client, headers, datos)
        resp = client.delete(f"{_RUTA}/{cambio_id}", headers=headers)
        assert resp.status_code == 405
