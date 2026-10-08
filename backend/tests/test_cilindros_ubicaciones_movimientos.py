"""
Tests de la subetapa 4.2: cilindros, ubicaciones y movimientos.

Ubicaciones (TAREA_29): `codigo` único e inmutable, estados
ACTIVA/INACTIVA y DELETE con cero referencias (cilindro y movimiento
origen/destino) → 409 HAS_HISTORY. Cilindros (TAREA_03): identidad
única e inmutable, nacen `REGISTRADO` (el `estado_operativo` y las FKs
no son editables), validación de FKs → 404 y DELETE solo sin historial
(8 tablas) → 409. Movimientos (TAREA_15 ∨ TAREA_16): `POST` atómico que
deriva `estado_anterior`/origen del servidor y actualiza el cilindro,
no-op → 400, reglas de la ubicación solo con cambio real de ubicación,
`Literal` de estado → 422 y router inmutable (405 en PATCH/DELETE).
"""

from __future__ import annotations

import uuid

import pytest
from factories import (
    TAREA_CAMBIO_UBICACION,
    TAREA_CATALOGOS,
    TAREA_CILINDROS,
    TAREA_MOVIMIENTOS,
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
    Movimiento,
    Permiso,
    Propietario,
    Tarea,
    TareaPermiso,
    TipoGas,
    Ubicacion,
)

_RUTA_UBICACIONES = "/api/v1/ubicaciones"
_RUTA_CILINDROS = "/api/v1/cilindros"
_RUTA_MOVIMIENTOS = "/api/v1/movimientos"
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _dominio(session_factory, *tareas: str):
    return await crear_cadena_rbac(session_factory, tareas=list(tareas), permisos=_PERMISOS)


# ============================================================
# HELPERS DE FIXTURES (directo en BD: cada test solo tiene su dominio)
# ============================================================


async def _ubicacion_bd(session_factory, **campos) -> uuid.UUID:
    p = prefijo()
    async with session_factory() as session:
        ubicacion = Ubicacion(
            codigo=f"UB{p[:10]}", nombre=f"Bodega {p[:6]}", tipo="INTERNA", **campos
        )
        session.add(ubicacion)
        await session.commit()
        return ubicacion.id


async def _datos_fk_bd(session_factory) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(propietario_id, tipo_gas_id, ubicacion_id) creados directo en BD."""
    p = prefijo()
    async with session_factory() as session:
        propietario = Propietario(tipo="AGAS", rut=f"7{p[:8]}", razon_social=f"Prop {p[:6]}")
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        ubicacion = Ubicacion(codigo=f"UB{p[:10]}", nombre=f"Bodega {p[:6]}", tipo="INTERNA")
        session.add_all([propietario, tipo_gas, ubicacion])
        await session.flush()
        ids = (propietario.id, tipo_gas.id, ubicacion.id)
        await session.commit()
    return ids


async def _cilindro_bd(
    session_factory, ubicacion_id: uuid.UUID, *, estado_operativo: str = "REGISTRADO"
) -> uuid.UUID:
    """Cilindro con sus FKs creados directo en BD (listo para mover)."""
    p = prefijo()
    async with session_factory() as session:
        propietario = Propietario(tipo="AGAS", rut=f"6{p[:8]}", razon_social=f"Prop {p[:6]}")
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        session.add_all([propietario, tipo_gas])
        await session.flush()
        cilindro = Cilindro(
            codigo_interno=f"CI{p[:10]}",
            numero_serie=f"NS{p[:10]}",
            codigo_qr=f"QR{p[:10]}",
            propietario_id=propietario.id,
            tipo_gas_id=tipo_gas.id,
            capacidad_kg=42,
            ubicacion_actual_id=ubicacion_id,
            estado_operativo=estado_operativo,
        )
        session.add(cilindro)
        await session.commit()
        return cilindro.id


def _body_cilindro(fk, **extra) -> dict:
    propietario_id, tipo_gas_id, ubicacion_id = fk
    p = prefijo()
    body = {
        "codigo_interno": f"CI{p[:10]}",
        "numero_serie": f"NS{p[:10]}",
        "codigo_qr": f"QR{p[:10]}",
        "propietario_id": str(propietario_id),
        "tipo_gas_id": str(tipo_gas_id),
        "ubicacion_actual_id": str(ubicacion_id),
        "capacidad_kg": 42,
    }
    body.update(extra)
    return body


async def _crear_cilindro_api(client, headers, fk, **extra) -> str:
    resp = client.post(_RUTA_CILINDROS, headers=headers, json=_body_cilindro(fk, **extra))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ============================================================
# GUARDS RBAC
# ============================================================


@pytest.mark.parametrize(
    "ruta",
    [_RUTA_UBICACIONES, _RUTA_CILINDROS, _RUTA_MOVIMIENTOS],
)
def test_4_2_sin_autenticacion_401(ruta: str) -> None:
    with TestClient(app) as client:
        resp = client.get(ruta)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


@pytest.mark.parametrize(
    ("tareas", "ruta"),
    [
        (["TAREA_03"], _RUTA_UBICACIONES),  # cilindros no administra el catálogo
        (["TAREA_29"], _RUTA_CILINDROS),  # catálogos no registran cilindros
        (["TAREA_03"], _RUTA_MOVIMIENTOS),  # TAREA_15/16 son los dominios del movimiento
        (["TAREA_29"], _RUTA_MOVIMIENTOS),
    ],
)
async def test_4_2_dominio_equivocado_403(session_factory, tareas: list[str], ruta: str) -> None:
    user, clave = await _dominio(session_factory, *tareas)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.get(ruta, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


# ============================================================
# UBICACIONES (TAREA_29)
# ============================================================


async def test_ubicacion_crud_completo(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CATALOGOS)
    p = prefijo()
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_UBICACIONES,
            headers=headers,
            json={
                "codigo": f"UB{p[:10]}",
                "nombre": f"Bodega {p[:6]}",
                "tipo": "CLIENTE",
                "descripcion": "Planta del cliente",
                "orden_visual": 5,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["estado"] == "ACTIVA"
        assert resp.json()["permite_entrada"] is True
        assert resp.json()["permite_salida"] is True
        rid = resp.json()["id"]

        assert client.get(f"{_RUTA_UBICACIONES}/{rid}", headers=headers).status_code == 200
        resp = client.get(_RUTA_UBICACIONES, headers=headers, params={"q": f"UB{p[:10]}"})
        assert resp.json()["total"] == 1

        # Actualización parcial (tipo mutable)
        resp = client.patch(
            f"{_RUTA_UBICACIONES}/{rid}",
            headers=headers,
            json={"nombre": "Bodega Norte", "tipo": "INTERNA", "permite_entrada": False},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["nombre"] == "Bodega Norte"
        assert resp.json()["tipo"] == "INTERNA"
        assert resp.json()["permite_entrada"] is False

        # Transición + filtro; misma transición → 409 con allowed_states
        resp = client.patch(f"{_RUTA_UBICACIONES}/{rid}/estado", headers=headers, json={"estado": "INACTIVA"})
        assert resp.status_code == 200
        resp = client.get(
            _RUTA_UBICACIONES, headers=headers, params={"q": f"UB{p[:10]}", "estado": "INACTIVA"}
        )
        assert resp.json()["total"] == 1
        resp = client.patch(f"{_RUTA_UBICACIONES}/{rid}/estado", headers=headers, json={"estado": "INACTIVA"})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == ["ACTIVA"]

        # Literal fuera de dominio → 422 y recuperación → 200
        resp = client.patch(f"{_RUTA_UBICACIONES}/{rid}/estado", headers=headers, json={"estado": "DESTRUIDA"})
        assert resp.status_code == 422
        resp = client.patch(f"{_RUTA_UBICACIONES}/{rid}/estado", headers=headers, json={"estado": "ACTIVA"})
        assert resp.status_code == 200

        assert client.delete(f"{_RUTA_UBICACIONES}/{rid}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA_UBICACIONES}/{rid}", headers=headers).status_code == 404


async def test_ubicacion_codigo_unico_e_inmutable(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CATALOGOS)
    codigo = f"UB{prefijo()[:10]}"
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_UBICACIONES, headers=headers, json={"codigo": codigo, "nombre": "Única"}
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        resp = client.post(
            _RUTA_UBICACIONES, headers=headers, json={"codigo": codigo, "nombre": "Duplicada"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # `codigo` fuera del Update → 400 (inmutable)
        resp = client.patch(f"{_RUTA_UBICACIONES}/{rid}", headers=headers, json={"codigo": "OTRO123"})
        assert resp.status_code == 400

        assert client.delete(f"{_RUTA_UBICACIONES}/{rid}", headers=headers).status_code == 204


async def test_ubicacion_null_significa_sin_cambio(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CATALOGOS)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_UBICACIONES, headers=headers, json={"codigo": f"UB{prefijo()[:10]}", "nombre": "Nulls"}
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        resp = client.patch(
            f"{_RUTA_UBICACIONES}/{rid}", headers=headers, json={"nombre": None, "descripcion": None}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.patch(
            f"{_RUTA_UBICACIONES}/{rid}", headers=headers, json={"nombre": "Cambiada", "descripcion": None}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["nombre"] == "Cambiada"

        assert client.delete(f"{_RUTA_UBICACIONES}/{rid}", headers=headers).status_code == 204


async def test_ubicacion_filtros_q_tipo_estado(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CATALOGOS)
    p = prefijo()
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_UBICACIONES,
            headers=headers,
            json={"codigo": f"UB{p[:10]}", "nombre": "Filtrable", "tipo": "CLIENTE"},
        )
        assert resp.status_code == 201, resp.text

        resp = client.get(
            _RUTA_UBICACIONES,
            headers=headers,
            params={"q": f"UB{p[:10]}", "tipo": "CLIENTE", "estado": "ACTIVA"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["codigo"] == f"UB{p[:10]}"


async def test_ubicacion_desconocida_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CATALOGOS)
    desconocida = str(uuid.uuid4())
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.get(f"{_RUTA_UBICACIONES}/{desconocida}", headers=headers).status_code == 404
        resp = client.patch(
            f"{_RUTA_UBICACIONES}/{desconocida}", headers=headers, json={"nombre": "x"}
        )
        assert resp.status_code == 404
        assert client.delete(f"{_RUTA_UBICACIONES}/{desconocida}", headers=headers).status_code == 404


async def test_ubicacion_delete_con_referencias_409(session_factory) -> None:
    """Con un cilindro ubicado en ella → 409; sin referencias → 204."""
    user, clave = await _dominio(session_factory, TAREA_CATALOGOS)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_UBICACIONES,
            headers=headers,
            json={"codigo": f"UB{prefijo()[:10]}", "nombre": "Con cilindro"},
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

    p = prefijo()
    async with session_factory() as session:
        propietario = Propietario(tipo="AGAS", rut=f"5{p[:8]}", razon_social=f"Prop {p[:6]}")
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre=f"Gas {p[:6]}")
        session.add_all([propietario, tipo_gas])
        await session.flush()
        cilindro = Cilindro(
            codigo_interno=f"CI{p[:10]}",
            numero_serie=f"NS{p[:10]}",
            codigo_qr=f"QR{p[:10]}",
            propietario_id=propietario.id,
            tipo_gas_id=tipo_gas.id,
            capacidad_kg=42,
            ubicacion_actual_id=uuid.UUID(rid),
        )
        session.add(cilindro)
        await session.commit()
        cilindro_id = cilindro.id

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.delete(f"{_RUTA_UBICACIONES}/{rid}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"

    async with session_factory() as session:
        cilindro = await session.get(Cilindro, cilindro_id)
        await session.delete(cilindro)
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.delete(f"{_RUTA_UBICACIONES}/{rid}", headers=headers).status_code == 204


async def test_ubicacion_delete_referencias_de_movimiento_409(session_factory) -> None:
    """Referenciada como origen y como destino de movimientos → 409 y 409."""
    user, clave = await _dominio(session_factory, TAREA_CATALOGOS)
    origen_id = await _ubicacion_bd(session_factory)
    destino_id = await _ubicacion_bd(session_factory)
    libre_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    async with session_factory() as session:
        session.add(
            Movimiento(
                cilindro_id=cilindro_id,
                ubicacion_origen_id=origen_id,
                ubicacion_destino_id=destino_id,
                estado_anterior="REGISTRADO",
                estado_nuevo="RECIBIDO",
            )
        )
        cilindro = await session.get(Cilindro, cilindro_id)
        cilindro.ubicacion_actual_id = destino_id
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        # Solo la referencia como origen del movimiento:
        assert client.delete(f"{_RUTA_UBICACIONES}/{origen_id}", headers=headers).status_code == 409

    async with session_factory() as session:
        cilindro = await session.get(Cilindro, cilindro_id)
        cilindro.ubicacion_actual_id = libre_id
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        # Solo la referencia como destino del movimiento:
        resp = client.delete(f"{_RUTA_UBICACIONES}/{destino_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"

    async with session_factory() as session:
        movimientos = (
            await session.execute(select(Movimiento).where(Movimiento.cilindro_id == cilindro_id))
        ).scalars().all()
        for movimiento in movimientos:
            await session.delete(movimiento)
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.delete(f"{_RUTA_UBICACIONES}/{destino_id}", headers=headers).status_code == 204


# ============================================================
# CILINDROS (TAREA_03)
# ============================================================


async def test_cilindro_crud_completo(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    fk = await _datos_fk_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_CILINDROS,
            headers=headers,
            json=_body_cilindro(
                fk,
                codigo_barras=f"CB{prefijo()[:10]}",
                marca="Linde",
                capacidad_kg=45,
                fecha_fabricacion="2024-01-15",
            ),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["estado_operativo"] == "REGISTRADO"
        rid = resp.json()["id"]
        codigo_interno = resp.json()["codigo_interno"]

        assert client.get(f"{_RUTA_CILINDROS}/{rid}", headers=headers).status_code == 200
        resp = client.get(_RUTA_CILINDROS, headers=headers, params={"q": codigo_interno})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == rid

        # Descriptivos + código de barras editable (único)
        nuevo_barras = f"CB{prefijo()[:10]}"
        resp = client.patch(
            f"{_RUTA_CILINDROS}/{rid}",
            headers=headers,
            json={"marca": "Hexagon", "capacidad_kg": 50, "codigo_barras": nuevo_barras},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["marca"] == "Hexagon"
        assert resp.json()["capacidad_kg"] == 50
        assert resp.json()["codigo_barras"] == nuevo_barras

        # Borrado físico con cero historial → 204 → 404
        assert client.delete(f"{_RUTA_CILINDROS}/{rid}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA_CILINDROS}/{rid}", headers=headers).status_code == 404


@pytest.mark.parametrize(
    "campo",
    ["propietario_id", "tipo_gas_id", "ubicacion_actual_id"],
)
async def test_cilindro_fk_desconocidas_404(session_factory, campo: str) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    fk = await _datos_fk_bd(session_factory)
    body = _body_cilindro(fk)
    body[campo] = str(uuid.uuid4())
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA_CILINDROS, headers=headers, json=body)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_cilindro_identidad_unica_e_inmutable(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    fk = await _datos_fk_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        base = _body_cilindro(fk)
        resp = client.post(_RUTA_CILINDROS, headers=headers, json=base)
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        # Cada identificador por separado → 409
        for campo in ("codigo_interno", "numero_serie", "codigo_qr"):
            body = _body_cilindro(fk)
            body[campo] = base[campo]
            resp = client.post(_RUTA_CILINDROS, headers=headers, json=body)
            assert resp.status_code == 409, f"{campo}: {resp.text}"
            assert codigo_error(resp) == "DUPLICATE_VALUE"

        # `codigo_barras` único pero editable: dup en alta y en PATCH
        barras = f"CB{prefijo()[:10]}"
        resp = client.post(_RUTA_CILINDROS, headers=headers, json=_body_cilindro(fk, codigo_barras=barras))
        assert resp.status_code == 201, resp.text
        otro_id = resp.json()["id"]
        resp = client.post(_RUTA_CILINDROS, headers=headers, json=_body_cilindro(fk, codigo_barras=barras))
        assert resp.status_code == 409
        resp = client.patch(
            f"{_RUTA_CILINDROS}/{rid}", headers=headers, json={"codigo_barras": barras}
        )
        assert resp.status_code == 409

        # Inmutables: fuera del Update → 400 si son lo único que se envía
        resp = client.patch(
            f"{_RUTA_CILINDROS}/{rid}", headers=headers, json={"codigo_interno": "CI-FALSOS"}
        )
        assert resp.status_code == 400

        client.delete(f"{_RUTA_CILINDROS}/{otro_id}", headers=headers)
        client.delete(f"{_RUTA_CILINDROS}/{rid}", headers=headers)


async def test_cilindro_campos_no_editables(session_factory) -> None:
    """`estado_operativo` y las FKs no se editan: solo vía movimientos."""
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    fk = await _datos_fk_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rid = await _crear_cilindro_api(client, headers, fk)

        for campo in ("estado_operativo", "ubicacion_actual_id", "propietario_id", "tipo_gas_id"):
            valor = "RECIBIDO" if campo == "estado_operativo" else str(uuid.uuid4())
            resp = client.patch(f"{_RUTA_CILINDROS}/{rid}", headers=headers, json={campo: valor})
            assert resp.status_code == 400, f"{campo}: {resp.text}"

        # Mezclado con un campo válido: solo se aplica lo válido y el estado no cambia
        resp = client.patch(
            f"{_RUTA_CILINDROS}/{rid}", headers=headers, json={"marca": "Tango", "estado_operativo": "RECIBIDO"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["marca"] == "Tango"
        assert resp.json()["estado_operativo"] == "REGISTRADO"

        client.delete(f"{_RUTA_CILINDROS}/{rid}", headers=headers)


@pytest.mark.parametrize("capacidad", [-1, 100_000_000])
async def test_cilindro_capacidad_invalida_422(session_factory, capacidad: float) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    fk = await _datos_fk_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_CILINDROS, headers=headers, json=_body_cilindro(fk, capacidad_kg=capacidad)
        )
        assert resp.status_code == 422


async def test_cilindro_null_significa_sin_cambio(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    fk = await _datos_fk_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rid = await _crear_cilindro_api(client, headers, fk)

        resp = client.patch(
            f"{_RUTA_CILINDROS}/{rid}", headers=headers, json={"marca": None, "color": None}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.patch(
            f"{_RUTA_CILINDROS}/{rid}", headers=headers, json={"marca": "Valeo", "color": None}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["marca"] == "Valeo"

        client.delete(f"{_RUTA_CILINDROS}/{rid}", headers=headers)


async def test_cilindro_filtros(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    fk = await _datos_fk_bd(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        body = _body_cilindro(fk)
        resp = client.post(_RUTA_CILINDROS, headers=headers, json=body)
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        resp = client.get(
            _RUTA_CILINDROS,
            headers=headers,
            params={
                "q": body["codigo_interno"],
                "estado_operativo": "REGISTRADO",
                "tipo_gas_id": str(fk[1]),
                "propietario_id": str(fk[0]),
                "ubicacion_actual_id": str(fk[2]),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == rid

        client.delete(f"{_RUTA_CILINDROS}/{rid}", headers=headers)


async def test_cilindro_delete_con_historial_409(session_factory) -> None:
    """Con un movimiento → 409 (y el mensaje sugiere DADO_DE_BAJA)."""
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    origen_id = await _ubicacion_bd(session_factory)
    destino_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    async with session_factory() as session:
        session.add(
            Movimiento(
                cilindro_id=cilindro_id,
                ubicacion_origen_id=origen_id,
                ubicacion_destino_id=destino_id,
                estado_anterior="REGISTRADO",
                estado_nuevo="RECIBIDO",
            )
        )
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.delete(f"{_RUTA_CILINDROS}/{cilindro_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"
        assert "DADO_DE_BAJA" in resp.json()["detail"]["message"]

    async with session_factory() as session:
        movimientos = (
            await session.execute(select(Movimiento).where(Movimiento.cilindro_id == cilindro_id))
        ).scalars().all()
        for movimiento in movimientos:
            await session.delete(movimiento)
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.delete(f"{_RUTA_CILINDROS}/{cilindro_id}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA_CILINDROS}/{cilindro_id}", headers=headers).status_code == 404


async def test_cilindro_desconocido_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CILINDROS)
    desconocido = str(uuid.uuid4())
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.get(f"{_RUTA_CILINDROS}/{desconocido}", headers=headers).status_code == 404
        resp = client.patch(
            f"{_RUTA_CILINDROS}/{desconocido}", headers=headers, json={"marca": "x"}
        )
        assert resp.status_code == 404
        assert client.delete(f"{_RUTA_CILINDROS}/{desconocido}", headers=headers).status_code == 404


# ============================================================
# MOVIMIENTOS (TAREA_15 ∨ TAREA_16)
# ============================================================


async def test_movimiento_cambio_ubicacion_atomico(session_factory) -> None:
    user, clave = await _dominio(
        session_factory, TAREA_CAMBIO_UBICACION, TAREA_MOVIMIENTOS
    )
    origen_id = await _ubicacion_bd(session_factory)
    destino_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "ubicacion_destino_id": str(destino_id),
                "estado_nuevo": "RECIBIDO",
                "motivo": "Recepción en bodega",
                "usuario_entrega_id": str(user.id),
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["ubicacion_origen_id"] == str(origen_id)
        assert resp.json()["ubicacion_destino_id"] == str(destino_id)
        assert resp.json()["estado_anterior"] == "REGISTRADO"
        assert resp.json()["estado_nuevo"] == "RECIBIDO"
        assert resp.json()["fecha_hora"] is not None
        movimiento_id = resp.json()["id"]

        # Atómico: el cilindro quedó en el destino con el nuevo estado (BD).
        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cilindro_id)
            assert cilindro.ubicacion_actual_id == destino_id
            assert cilindro.estado_operativo == "RECIBIDO"

        # Detalle + listados (sin filtros y con los 3 filtros).
        resp = client.get(f"{_RUTA_MOVIMIENTOS}/{movimiento_id}", headers=headers)
        assert resp.status_code == 200
        resp = client.get(_RUTA_MOVIMIENTOS, headers=headers)
        assert resp.status_code == 200
        resp = client.get(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            params={
                "cilindro_id": str(cilindro_id),
                "ubicacion_origen_id": str(origen_id),
                "ubicacion_destino_id": str(destino_id),
            },
        )
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == movimiento_id


async def test_movimiento_solo_estado_y_solo_ubicacion(session_factory) -> None:
    """Cambio puro de estado (destino = actual) y puro de ubicación."""
    user, clave = await _dominio(session_factory, TAREA_MOVIMIENTOS)
    origen_id = await _ubicacion_bd(session_factory)
    destino_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        # (a) Solo estado: destino = ubicación actual, sin mover.
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "ubicacion_destino_id": str(origen_id),
                "estado_nuevo": "DADO_DE_BAJA",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["ubicacion_origen_id"] == resp.json()["ubicacion_destino_id"]

        # (b) Solo ubicación: sin estado_nuevo se conserva el estado.
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "ubicacion_destino_id": str(destino_id),
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["estado_anterior"] == "DADO_DE_BAJA"
        assert resp.json()["estado_nuevo"] == "DADO_DE_BAJA"

        async with session_factory() as session:
            cilindro = await session.get(Cilindro, cilindro_id)
            assert cilindro.ubicacion_actual_id == destino_id
            assert cilindro.estado_operativo == "DADO_DE_BAJA"


async def test_movimiento_no_op_400(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_CAMBIO_UBICACION)
    origen_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        # Sin estado_nuevo y con destino = actual: nada cambia.
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "ubicacion_destino_id": str(origen_id)},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # Mismo destino y mismo estado explícito: también no-op.
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "ubicacion_destino_id": str(origen_id),
                "estado_nuevo": "REGISTRADO",
            },
        )
        assert resp.status_code == 400


async def test_movimiento_ubicacion_inactiva_400(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_MOVIMIENTOS)
    origen_id = await _ubicacion_bd(session_factory)
    destino_id = await _ubicacion_bd(session_factory, estado="INACTIVA")
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "ubicacion_destino_id": str(destino_id)},
        )
        assert resp.status_code == 400
        assert "ACTIVA" in resp.json()["detail"]["message"]


async def test_movimiento_permisos_de_ubicacion_400(session_factory) -> None:
    """`permite_entrada` del destino y `permite_salida` del origen."""
    user, clave = await _dominio(session_factory, TAREA_MOVIMIENTOS)

    # Destino que no admite entrada:
    origen_id = await _ubicacion_bd(session_factory)
    cerrada_id = await _ubicacion_bd(session_factory, permite_entrada=False)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "ubicacion_destino_id": str(cerrada_id)},
        )
        assert resp.status_code == 400
        assert "no permite entrada" in resp.json()["detail"]["message"]

    # Origen que no admite salida:
    salida_id = await _ubicacion_bd(session_factory, permite_salida=False)
    destino_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, salida_id)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "ubicacion_destino_id": str(destino_id)},
        )
        assert resp.status_code == 400
        assert "no permite salida" in resp.json()["detail"]["message"]


async def test_movimiento_estado_invalido_422(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_MOVIMIENTOS)
    origen_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "ubicacion_destino_id": str(origen_id),
                "estado_nuevo": "EXTRANJO",
            },
        )
        assert resp.status_code == 422


async def test_movimiento_referencias_404(session_factory) -> None:
    user, clave = await _dominio(session_factory, TAREA_MOVIMIENTOS)
    origen_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(uuid.uuid4()),
                "ubicacion_destino_id": str(origen_id),
            },
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "ubicacion_destino_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 404

        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={
                "cilindro_id": str(cilindro_id),
                "ubicacion_destino_id": str(origen_id),
                "estado_nuevo": "RECIBIDO",
                "usuario_entrega_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 404


async def test_movimiento_router_inmutable_405(session_factory) -> None:
    """La trazabilidad no se edita ni se borra: solo GET y POST."""
    user, clave = await _dominio(session_factory, TAREA_MOVIMIENTOS)
    origen_id = await _ubicacion_bd(session_factory)
    cilindro_id = await _cilindro_bd(session_factory, origen_id)

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_MOVIMIENTOS,
            headers=headers,
            json={"cilindro_id": str(cilindro_id), "ubicacion_destino_id": str(origen_id),
                  "estado_nuevo": "RECIBIDO"},
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        resp = client.patch(f"{_RUTA_MOVIMIENTOS}/{rid}", headers=headers, json={"motivo": "x"})
        assert resp.status_code == 405
        assert client.delete(f"{_RUTA_MOVIMIENTOS}/{rid}", headers=headers).status_code == 405


async def test_movimiento_guard_tarea_15_o_16(session_factory) -> None:
    """Cualquiera de los dos dominios habilita POST/GET (guard OR)."""
    origen_id = await _ubicacion_bd(session_factory)
    destino_id = await _ubicacion_bd(session_factory)

    for tarea in (TAREA_CAMBIO_UBICACION, TAREA_MOVIMIENTOS):
        user, clave = await _dominio(session_factory, tarea)
        cilindro_id = await _cilindro_bd(session_factory, origen_id)
        with TestClient(app) as client:
            headers = _admin(client, user, clave)
            resp = client.post(
                _RUTA_MOVIMIENTOS,
                headers=headers,
                json={"cilindro_id": str(cilindro_id), "ubicacion_destino_id": str(destino_id)},
            )
            assert resp.status_code == 201, f"{tarea}: {resp.text}"
            # El dominio con la tarea también puede consultar el historial.
            resp = client.get(_RUTA_MOVIMIENTOS, headers=headers, params={"cilindro_id": str(cilindro_id)})
            assert resp.status_code == 200
            assert resp.json()["total"] == 1


async def test_movimiento_sin_permiso_403(session_factory) -> None:
    """Con la tarea pero sin PERM_01 en la matriz → 403 que menciona el permiso."""
    user, clave = await _dominio(session_factory, TAREA_MOVIMIENTOS)

    # Revoca PERM_01 en la matriz (se restaura en finally para no
    # contaminar a otros tests: la matriz es global en la BD de pruebas).
    async with session_factory() as session:
        tarea = (
            await session.execute(select(Tarea).where(Tarea.codigo == TAREA_MOVIMIENTOS))
        ).scalar_one()
        permiso = (
            await session.execute(select(Permiso).where(Permiso.codigo == "PERM_01"))
        ).scalar_one()
        claves = (tarea.id, permiso.id)
        fila = await session.get(TareaPermiso, claves)
        assert fila is not None
        fila.concedido = False
        await session.commit()

    try:
        with TestClient(app) as client:
            headers = _admin(client, user, clave)
            resp = client.get(_RUTA_MOVIMIENTOS, headers=headers)
            assert resp.status_code == 403
            assert codigo_error(resp) == "PERMISSION_DENIED"
            assert "PERM_01" in resp.json()["detail"]["message"]
    finally:
        async with session_factory() as session:
            fila = await session.get(TareaPermiso, claves)
            if fila is not None:
                fila.concedido = True
                await session.commit()
