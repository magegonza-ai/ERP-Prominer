"""
Tests de la subetapa 5.2: inspección de cilindros.

Inspección (TAREA_05): **append-only** (POST + GET; PATCH/DELETE → 405),
`usuario_id` = usuario autenticado y `fecha_hora` del servidor; `cilindro_id`
obligatorio (404) y `recepcion_id` vínculo informativo (404); `resultado` y
el checklist se validan con `Literal`/`bool` (422). Cada alta emite un
`Movimiento` atómico que mapea el `resultado` al estado del cilindro
(`APTO_LLENADO`→`APTO_LLENADO`, `REQUIERE_REPARACION`→`APTO_REPARACION`,
`REQUIERE_INSPECCION_TECNICA`→`PENDIENTE_INSPECCION`, `RECHAZADO`→`RECHAZADO`,
`FUERA_SERVICIO`→`FUERA_SERVICIO`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from factories import (
    TAREA_INSPECCION,
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
    Recepcion,
    Tarea,
    TareaPermiso,
    TipoGas,
    Ubicacion,
)

_RUTA = "/api/v1/inspecciones"
_PERMISOS = ["PERM_01", "PERM_02"]


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _dominio(session_factory, *tareas: str):
    return await crear_cadena_rbac(session_factory, tareas=list(tareas), permisos=_PERMISOS)


# ============================================================
# HELPERS DE FIXTURES (directo en BD)
# ============================================================


async def _datos_base(session_factory, *, estado_operativo: str = "RECIBIDO") -> dict:
    """Crea propietario, tipo de gas, ubicación, cliente y un cilindro."""
    p = prefijo()
    async with session_factory() as session:
        propietario = Propietario(tipo="AGAS", rut=f"2{p[:8]}", razon_social=f"Prop {p[:6]}")
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        ubicacion = Ubicacion(codigo=f"UB{p[:10]}", nombre=f"Bodega {p[:6]}", tipo="INTERNA")
        cliente = Cliente(rut=f"1{p[:8]}", razon_social=f"Cliente {p[:6]}")
        session.add_all([propietario, tipo_gas, ubicacion, cliente])
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
        return {
            "propietario_id": propietario.id,
            "tipo_gas_id": tipo_gas.id,
            "ubicacion_id": ubicacion.id,
            "cliente_id": cliente.id,
            "cilindro_id": cilindro.id,
        }


async def _recepcion_bd(session_factory, datos: dict, usuario_id: uuid.UUID) -> uuid.UUID:
    async with session_factory() as session:
        recepcion = Recepcion(
            numero=f"REC-TEST-{prefijo()}",
            cliente_entrega_id=datos["cliente_id"],
            propietario_id=datos["propietario_id"],
            usuario_responsable_id=usuario_id,
            motivo_servicio="LLENADO",
        )
        session.add(recepcion)
        await session.commit()
        return recepcion.id


def _body(cilindro_id, resultado: str, **extra) -> dict:
    body = {"cilindro_id": str(cilindro_id), "resultado": resultado}
    body.update(extra)
    return body


# ============================================================
# GUARDS RBAC
# ============================================================


def test_inspeccion_sin_autenticacion_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


async def test_inspeccion_dominio_equivocado_403(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_RECEPCION)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


async def test_inspeccion_sin_permiso_403(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory)

    async with session_factory() as session:
        tarea = (await session.execute(select(Tarea).where(Tarea.codigo == TAREA_INSPECCION))).scalar_one()
        permiso = (await session.execute(select(Permiso).where(Permiso.codigo == "PERM_02"))).scalar_one()
        claves = (tarea.id, permiso.id)
        fila = await session.get(TareaPermiso, claves)
        assert fila is not None
        fila.concedido = False
        await session.commit()

    try:
        with TestClient(app) as client:
            headers = _admin(client, user, clave)
            resp = client.post(_RUTA, headers=headers, json=_body(datos["cilindro_id"], "APTO_LLENADO"))
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
# ALTA + MOVIMIENTO
# ============================================================


async def test_inspeccion_alta_completa_y_movimiento(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory, estado_operativo="RECIBIDO")
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body(
                datos["cilindro_id"],
                "APTO_LLENADO",
                estado_general="BUENO",
                pintura_ok=True,
                corrosion_nivel="LEVE",
                abolladuras=False,
                valvula_estado="BUENO",
                fugas_detectadas=False,
                serie_legible=True,
                prueba_hidraulica_vigente=True,
                gas_compatible=True,
                observaciones="Sin novedades",
                fotografias={"frontal": "ok"},
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["usuario_id"] == str(user.id)
        assert data["fecha_hora"] is not None
        assert data["resultado"] == "APTO_LLENADO"
        assert data["corrosion_nivel"] == "LEVE"
        assert data["fotografias"] == {"frontal": "ok"}
        inspeccion_id = data["id"]

        # El movimiento y el estado quedaron registrados (atómico).
        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindro_id"])
            assert cilindro.estado_operativo == "APTO_LLENADO"
            movimiento = (
                await session.execute(
                    select(Movimiento).where(Movimiento.cilindro_id == datos["cilindro_id"])
                )
            ).scalar_one()
            assert movimiento.estado_anterior == "RECIBIDO"
            assert movimiento.estado_nuevo == "APTO_LLENADO"
            assert movimiento.usuario_recibe_id == user.id
            assert "APTO_LLENADO" in movimiento.motivo

        # Detalle y listado con filtros.
        assert client.get(f"{_RUTA}/{inspeccion_id}", headers=headers).status_code == 200
        resp = client.get(
            _RUTA,
            headers=headers,
            params={
                "cilindro_id": str(datos["cilindro_id"]),
                "resultado": "APTO_LLENADO",
                "usuario_id": str(user.id),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == inspeccion_id


@pytest.mark.parametrize(
    ("resultado", "estado_esperado"),
    [
        ("APTO_LLENADO", "APTO_LLENADO"),
        ("REQUIERE_REPARACION", "APTO_REPARACION"),
        ("REQUIERE_INSPECCION_TECNICA", "PENDIENTE_INSPECCION"),
        ("RECHAZADO", "RECHAZADO"),
        ("FUERA_SERVICIO", "FUERA_SERVICIO"),
    ],
)
async def test_inspeccion_mapeo_resultado_a_estado(session_factory, resultado: str, estado_esperado: str) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory, estado_operativo="PENDIENTE_INSPECCION")
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=_body(datos["cilindro_id"], resultado))
        assert resp.status_code == 201, resp.text

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindro_id"])
            assert cilindro.estado_operativo == estado_esperado
            movimiento = (
                await session.execute(
                    select(Movimiento).where(Movimiento.cilindro_id == datos["cilindro_id"])
                )
            ).scalar_one()
            assert movimiento.estado_anterior == "PENDIENTE_INSPECCION"
            assert movimiento.estado_nuevo == estado_esperado


async def test_inspeccion_con_recepcion_valida(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory)
    recepcion_id = await _recepcion_bd(session_factory, datos, user.id)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body(datos["cilindro_id"], "APTO_LLENADO", recepcion_id=str(recepcion_id)),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["recepcion_id"] == str(recepcion_id)

        resp = client.get(_RUTA, headers=headers, params={"recepcion_id": str(recepcion_id)})
        assert resp.json()["total"] == 1


async def test_inspeccion_cadena_desde_recepcion(session_factory) -> None:
    """Recepción deja el cilindro en RECIBIDO; la inspección parte de ahí."""
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory, estado_operativo="REGISTRADO")
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        # Simula la recepción (movimiento REGISTRADO -> RECIBIDO).
        async with session_factory() as session:
            cilindro = await session.get(Cilindro, datos["cilindro_id"])
            session.add(
                Movimiento(
                    cilindro_id=cilindro.id,
                    ubicacion_origen_id=cilindro.ubicacion_actual_id,
                    ubicacion_destino_id=cilindro.ubicacion_actual_id,
                    estado_anterior="REGISTRADO",
                    estado_nuevo="RECIBIDO",
                    usuario_recibe_id=user.id,
                    motivo="Recepción previa",
                )
            )
            cilindro.estado_operativo = "RECIBIDO"
            await session.commit()

        resp = client.post(_RUTA, headers=headers, json=_body(datos["cilindro_id"], "APTO_LLENADO"))
        assert resp.status_code == 201, resp.text

        async with session_factory() as session:
            movimientos = (
                await session.execute(
                    select(Movimiento)
                    .where(Movimiento.cilindro_id == datos["cilindro_id"])
                    .order_by(Movimiento.fecha_hora)
                )
            ).scalars().all()
            assert [m.estado_nuevo for m in movimientos] == ["RECIBIDO", "APTO_LLENADO"]


# ============================================================
# VALIDACIONES
# ============================================================


async def test_inspeccion_cilindro_desconocido_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=_body(uuid.uuid4(), "APTO_LLENADO"))
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_inspeccion_recepcion_desconocida_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA,
            headers=headers,
            json=_body(datos["cilindro_id"], "APTO_LLENADO", recepcion_id=str(uuid.uuid4())),
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_inspeccion_resultado_invalido_422(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=_body(datos["cilindro_id"], "PERFECTO"))
        assert resp.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"estado_general": "EXCELENTE"},
        {"corrosion_nivel": "MUCHA"},
        {"valvula_estado": "ROTA"},
        {"pintura_ok": "si"},
    ],
)
async def test_inspeccion_checklist_invalido_422(session_factory, extra: dict) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA, headers=headers, json=_body(datos["cilindro_id"], "APTO_LLENADO", **extra)
        )
        assert resp.status_code == 422


async def test_inspeccion_desconocida_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


# ============================================================
# APPEND-ONLY (405 en PATCH/DELETE)
# ============================================================


async def test_inspeccion_append_only_405(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=_body(datos["cilindro_id"], "APTO_LLENADO"))
        assert resp.status_code == 201, resp.text
        inspeccion_id = resp.json()["id"]
        assert client.patch(f"{_RUTA}/{inspeccion_id}", headers=headers, json={}).status_code == 405
        assert client.delete(f"{_RUTA}/{inspeccion_id}", headers=headers).status_code == 405


# ============================================================
# FILTROS DE FECHA
# ============================================================


async def test_inspeccion_filtro_fechas(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_INSPECCION)
    datos = await _datos_base(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA, headers=headers, json=_body(datos["cilindro_id"], "APTO_LLENADO"))
        assert resp.status_code == 201, resp.text

        ahora = datetime.now(UTC)
        dentro = client.get(
            _RUTA,
            headers=headers,
            params={
                "desde": (ahora - timedelta(hours=1)).isoformat(),
                "hasta": (ahora + timedelta(hours=1)).isoformat(),
            },
        )
        assert dentro.json()["total"] >= 1

        fuera = client.get(
            _RUTA, headers=headers, params={"desde": (ahora + timedelta(hours=1)).isoformat()}
        )
        assert fuera.json()["total"] == 0
