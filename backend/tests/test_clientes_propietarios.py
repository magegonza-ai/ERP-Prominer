"""
Tests de la subetapa 4.1: clientes, receptores autorizados y propietarios.

Clientes: `rut` único e inmutable, estados ACTIVO/INACTIVO/BLOQUEADO y
DELETE solo con cero referencias externas (409 HAS_HISTORY). Receptores:
sub-recurso anidado acotado a su cliente (404 cruzado), `autorizado_por`
= usuario autenticado, vigencia no anterior a la fecha de autorización
(400) y cascada al borrar el cliente. Propietarios: `tipo`/`rut`
inmutables, unicidad parcial `(rut, tipo)` solo para `tipo ≠ CLIENTE`,
vínculo `cliente_id` obligatorio en tipo CLIENTE (404/409) y prohibido en
los demás (400), DELETE con historial → 409. Guards TAREA_01/TAREA_02.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from factories import (
    TAREA_CATALOGOS,
    TAREA_CLIENTES,
    TAREA_PROPIETARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    prefijo,
    token_de,
)
from fastapi.testclient import TestClient

from app.main import app
from app.models import Cilindro, TipoGas, Ubicacion

_RUTA_CLIENTES = "/api/v1/clientes"
_RUTA_PROPIETARIOS = "/api/v1/propietarios"
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]

HOY = date.today()


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _admin_maestros(session_factory):
    """Dominio 4.1: clientes (TAREA_01) + propietarios (TAREA_02)."""
    return await crear_cadena_rbac(
        session_factory,
        tareas=[TAREA_CLIENTES, TAREA_PROPIETARIOS],
        permisos=_PERMISOS,
    )


def _body_cliente(**extra) -> dict:
    return {
        "rut": f"9{prefijo()[:8]}",
        "razon_social": f"Empresa {prefijo()[:6]}",
        **extra,
    }


def _body_propietario(tipo: str = "AGAS", **extra) -> dict:
    return {
        "tipo": tipo,
        "rut": f"8{prefijo()[:8]}",
        "razon_social": f"Propietario {prefijo()[:6]}",
        **extra,
    }


async def _crear_cliente(client: TestClient, headers: dict) -> str:
    resp = client.post(_RUTA_CLIENTES, headers=headers, json=_body_cliente())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ============================================================
# GUARDS RBAC
# ============================================================


@pytest.mark.parametrize("ruta", [_RUTA_CLIENTES, _RUTA_PROPIETARIOS])
def test_4_1_sin_token_401(ruta: str) -> None:
    with TestClient(app) as client:
        resp = client.get(ruta)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


@pytest.mark.parametrize("ruta", [_RUTA_CLIENTES, _RUTA_PROPIETARIOS])
async def test_4_1_dominio_equivocado_403(session_factory, ruta: str) -> None:
    """TAREA_29 (catálogos) no da acceso a TAREA_01/02 (maestros 4.1)."""
    user, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS
    )
    with TestClient(app) as client:
        resp = client.get(ruta, headers=_admin(client, user, clave))
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


async def test_receptores_dominio_equivocado_403(session_factory) -> None:
    """TAREA_02 (propietarios) no habilita los receptores (TAREA_01)."""
    user, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_PROPIETARIOS], permisos=_PERMISOS
    )
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        aleatorio = str(uuid.uuid4())
        resp = client.get(f"{_RUTA_CLIENTES}/{aleatorio}/receptores-autorizados", headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


# ============================================================
# CLIENTES
# ============================================================


async def test_cliente_crud_completo(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rut = f"9{prefijo()[:8]}"

        # Alta con default ACTIVO
        resp = client.post(_RUTA_CLIENTES, headers=headers, json=_body_cliente(rut=rut))
        assert resp.status_code == 201, resp.text
        creado = resp.json()
        rid = creado["id"]
        assert creado["rut"] == rut
        assert creado["estado"] == "ACTIVO"

        # Detalle + listado por `q` (único por el RUT)
        assert client.get(f"{_RUTA_CLIENTES}/{rid}", headers=headers).json()["id"] == rid
        resp = client.get(_RUTA_CLIENTES, headers=headers, params={"q": rut})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == rid

        # Actualización parcial
        resp = client.patch(
            f"{_RUTA_CLIENTES}/{rid}",
            headers=headers,
            json={"razon_social": "Empresa Renombrada", "ciudad": "Temuco"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["razon_social"] == "Empresa Renombrada"
        assert resp.json()["ciudad"] == "Temuco"

        # Transición a INACTIVO + filtro; misma transición → 409
        resp = client.patch(f"{_RUTA_CLIENTES}/{rid}/estado", headers=headers, json={"estado": "INACTIVO"})
        assert resp.status_code == 200
        resp = client.get(_RUTA_CLIENTES, headers=headers, params={"q": rut, "estado": "INACTIVO"})
        assert resp.json()["total"] == 1
        resp = client.patch(f"{_RUTA_CLIENTES}/{rid}/estado", headers=headers, json={"estado": "INACTIVO"})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == ["ACTIVO", "BLOQUEADO"]

        # Borrado físico (cero referencias) y detalle posterior → 404
        assert client.delete(f"{_RUTA_CLIENTES}/{rid}", headers=headers).status_code == 204
        resp = client.get(f"{_RUTA_CLIENTES}/{rid}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_cliente_rut_duplicado_e_inmutable(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rut = f"9{prefijo()[:8]}"
        body = _body_cliente(rut=rut)
        assert client.post(_RUTA_CLIENTES, headers=headers, json=body).status_code == 201

        resp = client.post(_RUTA_CLIENTES, headers=headers, json=body)
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # `rut` no está en el esquema Update → nada que actualizar
        rid = client.get(_RUTA_CLIENTES, headers=headers, params={"q": rut}).json()["items"][0]["id"]
        resp = client.patch(f"{_RUTA_CLIENTES}/{rid}", headers=headers, json={"rut": "1.111.111-1"})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_CLIENTES}/{rid}", headers=headers)


async def test_cliente_transicion_recuperacion_y_invalida(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rid = await _crear_cliente(client, headers)

        assert client.patch(
            f"{_RUTA_CLIENTES}/{rid}/estado", headers=headers, json={"estado": "BLOQUEADO"}
        ).status_code == 200
        assert client.patch(
            f"{_RUTA_CLIENTES}/{rid}/estado", headers=headers, json={"estado": "ACTIVO"}
        ).status_code == 200  # recuperación válida

        resp = client.patch(f"{_RUTA_CLIENTES}/{rid}/estado", headers=headers, json={"estado": "OTRO"})
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_CLIENTES}/{rid}", headers=headers)


async def test_cliente_null_significa_sin_cambio(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rid = await _crear_cliente(client, headers)

        resp = client.patch(f"{_RUTA_CLIENTES}/{rid}", headers=headers, json={"razon_social": None})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.patch(
            f"{_RUTA_CLIENTES}/{rid}",
            headers=headers,
            json={"razon_social": None, "observaciones": "obs"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["observaciones"] == "obs"

        client.delete(f"{_RUTA_CLIENTES}/{rid}", headers=headers)


async def test_cliente_delete_con_referencias_409(session_factory) -> None:
    """Con un propietario vinculado → 409; retirado el vínculo → 204."""
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cliente_id = await _crear_cliente(client, headers)

        resp = client.post(
            _RUTA_PROPIETARIOS,
            headers=headers,
            json=_body_propietario(tipo="CLIENTE", cliente_id=cliente_id),
        )
        assert resp.status_code == 201, resp.text
        propietario_id = resp.json()["id"]

        resp = client.delete(f"{_RUTA_CLIENTES}/{cliente_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"

        assert client.delete(f"{_RUTA_PROPIETARIOS}/{propietario_id}", headers=headers).status_code == 204
        assert client.delete(f"{_RUTA_CLIENTES}/{cliente_id}", headers=headers).status_code == 204


async def test_cliente_desconocido_404(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        inexistente = str(uuid.uuid4())
        assert client.get(f"{_RUTA_CLIENTES}/{inexistente}", headers=headers).status_code == 404
        assert (
            client.patch(f"{_RUTA_CLIENTES}/{inexistente}", headers=headers, json={"razon_social": "x"}).status_code
            == 404
        )
        assert client.delete(f"{_RUTA_CLIENTES}/{inexistente}", headers=headers).status_code == 404


# ============================================================
# RECEPTORES AUTORIZADOS (sub-recurso anidado)
# ============================================================


async def test_receptor_crud_anidado(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cliente_id = await _crear_cliente(client, headers)
        base = f"{_RUTA_CLIENTES}/{cliente_id}/receptores-autorizados"

        # Alta: autorizado_por = usuario autenticado, fecha = hoy, VIGENTE
        resp = client.post(base, headers=headers, json={"nombre": "Chofer Test", "relacion": "CHOFER"})
        assert resp.status_code == 201, resp.text
        creado = resp.json()
        rid = creado["id"]
        assert creado["cliente_id"] == cliente_id
        assert creado["autorizado_por"] == str(user.id)
        assert creado["fecha_autorizacion"] == HOY.isoformat()
        assert creado["estado"] == "VIGENTE"

        # Listado paginado acotado + detalle
        resp = client.get(base, headers=headers, params={"q": "Chofer"})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == rid
        assert client.get(f"{base}/{rid}", headers=headers).json()["id"] == rid

        # Actualización + transición de estado (misma → 409)
        resp = client.patch(f"{base}/{rid}", headers=headers, json={"telefono": "912345678"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["telefono"] == "912345678"
        resp = client.patch(f"{base}/{rid}/estado", headers=headers, json={"estado": "VENCIDO"})
        assert resp.status_code == 200
        resp = client.get(base, headers=headers, params={"estado": "VENCIDO"})
        assert resp.json()["total"] == 1
        resp = client.patch(f"{base}/{rid}/estado", headers=headers, json={"estado": "VENCIDO"})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == ["VIGENTE", "REVOCADO"]

        # Borrado físico y detalle posterior → 404
        assert client.delete(f"{base}/{rid}", headers=headers).status_code == 204
        assert client.get(f"{base}/{rid}", headers=headers).status_code == 404


async def test_receptor_cliente_desconocido_404(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        base = f"{_RUTA_CLIENTES}/{uuid.uuid4()}/receptores-autorizados"
        assert client.get(base, headers=headers).status_code == 404
        resp = client.post(base, headers=headers, json={"nombre": "Sin cliente"})
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_receptor_acotado_a_su_cliente_404(session_factory) -> None:
    """Un receptor de A no es visible ni modificable bajo el cliente B."""
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cliente_a = await _crear_cliente(client, headers)
        cliente_b = await _crear_cliente(client, headers)

        resp = client.post(
            f"{_RUTA_CLIENTES}/{cliente_a}/receptores-autorizados",
            headers=headers,
            json={"nombre": "De A"},
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        base_b = f"{_RUTA_CLIENTES}/{cliente_b}/receptores-autorizados"
        assert client.get(f"{base_b}/{rid}", headers=headers).status_code == 404
        assert (
            client.patch(f"{base_b}/{rid}", headers=headers, json={"nombre": "usurpado"}).status_code == 404
        )
        assert client.delete(f"{base_b}/{rid}", headers=headers).status_code == 404

        # Sigue vivo bajo su cliente real
        base_a = f"{_RUTA_CLIENTES}/{cliente_a}/receptores-autorizados"
        assert client.get(f"{base_a}/{rid}", headers=headers).status_code == 200
        client.delete(f"{base_a}/{rid}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_a}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_b}", headers=headers)


async def test_receptor_vigencia_invalida_400(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cliente_id = await _crear_cliente(client, headers)
        base = f"{_RUTA_CLIENTES}/{cliente_id}/receptores-autorizados"
        ayer = (HOY - timedelta(days=1)).isoformat()

        resp = client.post(base, headers=headers, json={"nombre": "X", "vigente_hasta": ayer})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.post(base, headers=headers, json={"nombre": "Y"})
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]
        resp = client.patch(f"{base}/{rid}", headers=headers, json={"vigente_hasta": ayer})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{base}/{rid}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_id}", headers=headers)


async def test_receptor_null_y_estado_invalido(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        cliente_id = await _crear_cliente(client, headers)
        base = f"{_RUTA_CLIENTES}/{cliente_id}/receptores-autorizados"
        rid = client.post(base, headers=headers, json={"nombre": "Original"}).json()["id"]

        # `null` = sin cambio
        resp = client.patch(f"{base}/{rid}", headers=headers, json={"nombre": None})
        assert resp.status_code == 400
        resp = client.patch(f"{base}/{rid}", headers=headers, json={"nombre": None, "correo": "x@y.cl"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["nombre"] == "Original"

        # Estado fuera del Literal → 422
        resp = client.patch(f"{base}/{rid}/estado", headers=headers, json={"estado": "ACTIVO"})
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{base}/{rid}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_id}", headers=headers)


async def test_delete_cliente_en_cascada_receptores(session_factory) -> None:
    """El borrado del cliente se lleva sus receptores (delete-orphan)."""
    user, clave = await _admin_maestros(session_factory)
    async with session_factory() as session:
        from sqlalchemy import func, select

        from app.models import ClienteReceptorAutorizado

        with TestClient(app) as client:
            headers = _admin(client, user, clave)
            cliente_id = await _crear_cliente(client, headers)
            resp = client.post(
                f"{_RUTA_CLIENTES}/{cliente_id}/receptores-autorizados",
                headers=headers,
                json={"nombre": "Se va con el cliente"},
            )
            assert resp.status_code == 201, resp.text
            assert client.delete(f"{_RUTA_CLIENTES}/{cliente_id}", headers=headers).status_code == 204

        restantes = (
            await session.execute(
                select(func.count())
                .select_from(ClienteReceptorAutorizado)
                .where(ClienteReceptorAutorizado.cliente_id == uuid.UUID(cliente_id))
            )
        ).scalar_one()
        assert restantes == 0


# ============================================================
# PROPIETARIOS
# ============================================================


async def test_propietario_crud_agas(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        # Alta tipo AGAS sin vínculo (defaults)
        resp = client.post(_RUTA_PROPIETARIOS, headers=headers, json=_body_propietario())
        assert resp.status_code == 201, resp.text
        creado = resp.json()
        rid = creado["id"]
        assert creado["tipo"] == "AGAS"
        assert creado["cliente_id"] is None
        assert creado["es_institucional_agas"] is False
        assert creado["estado"] == "ACTIVO"

        # Detalle + filtros `q` y `tipo`
        assert client.get(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers).json()["id"] == rid
        resp = client.get(
            _RUTA_PROPIETARIOS, headers=headers, params={"q": creado["rut"], "tipo": "AGAS"}
        )
        assert resp.json()["total"] == 1
        resp = client.get(
            _RUTA_PROPIETARIOS, headers=headers, params={"q": creado["rut"], "tipo": "CLIENTE"}
        )
        assert resp.json()["total"] == 0

        # Actualización + estado
        resp = client.patch(
            f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers, json={"razon_social": "AGAS SpA"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["razon_social"] == "AGAS SpA"
        resp = client.patch(f"{_RUTA_PROPIETARIOS}/{rid}/estado", headers=headers, json={"estado": "INACTIVO"})
        assert resp.status_code == 200
        resp = client.get(
            _RUTA_PROPIETARIOS, headers=headers, params={"q": creado["rut"], "estado": "INACTIVO"}
        )
        assert resp.json()["total"] == 1

        # Borrado físico y detalle posterior → 404
        assert client.delete(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers).status_code == 404


async def test_propietario_tipo_cliente_reglas_vinculo(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        # Tipo CLIENTE exige cliente_id → 400
        resp = client.post(_RUTA_PROPIETARIOS, headers=headers, json=_body_propietario(tipo="CLIENTE"))
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # cliente_id inexistente → 404
        resp = client.post(
            _RUTA_PROPIETARIOS,
            headers=headers,
            json=_body_propietario(tipo="CLIENTE", cliente_id=str(uuid.uuid4())),
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        # Vínculo válido → 201; segundo propietario sobre el mismo cliente → 409
        cliente_id = await _crear_cliente(client, headers)
        resp = client.post(
            _RUTA_PROPIETARIOS,
            headers=headers,
            json=_body_propietario(tipo="CLIENTE", cliente_id=cliente_id),
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]
        resp = client.post(
            _RUTA_PROPIETARIOS,
            headers=headers,
            json=_body_propietario(tipo="CLIENTE", cliente_id=cliente_id),
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # Cambiar el vínculo a otro cliente libre (el chequeo excluye el propio id)…
        cliente_b = await _crear_cliente(client, headers)
        resp = client.patch(
            f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers, json={"cliente_id": cliente_b}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cliente_id"] == cliente_b
        # …y volver al original, que queda libre tras moverse
        resp = client.patch(
            f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers, json={"cliente_id": cliente_id}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cliente_id"] == cliente_id

        client.delete(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_b}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_id}", headers=headers)


async def test_propietario_sin_vinculo_no_cliente(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        # Tipo AGAS/EMPRESA_EXTERNA no admite cliente_id → 400
        cliente_id = await _crear_cliente(client, headers)
        resp = client.post(
            _RUTA_PROPIETARIOS,
            headers=headers,
            json=_body_propietario(tipo="AGAS", cliente_id=cliente_id),
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # Y en PATCH: mandar un vínculo sobre un AGAS → 400
        resp = client.post(_RUTA_PROPIETARIOS, headers=headers, json=_body_propietario())
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]
        resp = client.patch(
            f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers, json={"cliente_id": cliente_id}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_id}", headers=headers)


async def test_propietario_rut_unico_parcial_por_tipo(session_factory) -> None:
    """`(rut, tipo)` único solo para `tipo ≠ CLIENTE`: clientes admiten repetir."""
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rut = f"7{prefijo()[:8]}"

        # Mismo RUT en dos tipos no CLIENTE no choca entre sí...
        assert (
            client.post(_RUTA_PROPIETARIOS, headers=headers, json=_body_propietario(tipo="AGAS", rut=rut)).status_code
            == 201
        )
        resp = client.post(
            _RUTA_PROPIETARIOS,
            headers=headers,
            json=_body_propietario(tipo="EMPRESA_EXTERNA", rut=rut),
        )
        assert resp.status_code == 201, resp.text
        rids = [
            p["id"]
            for p in client.get(_RUTA_PROPIETARIOS, headers=headers, params={"q": rut}).json()["items"]
        ]
        assert len(rids) == 2

        # ...pero repetir dentro del mismo tipo → 409
        resp = client.post(
            _RUTA_PROPIETARIOS, headers=headers, json=_body_propietario(tipo="AGAS", rut=rut)
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # Dos propietarios tipo CLIENTE con el mismo RUT (clientes distintos) → 201
        cliente_a = await _crear_cliente(client, headers)
        cliente_b = await _crear_cliente(client, headers)
        for cid in (cliente_a, cliente_b):
            resp = client.post(
                _RUTA_PROPIETARIOS,
                headers=headers,
                json=_body_propietario(tipo="CLIENTE", rut=rut, cliente_id=cid),
            )
            assert resp.status_code == 201, resp.text
            rids.append(resp.json()["id"])

        for rid in rids:
            client.delete(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_a}", headers=headers)
        client.delete(f"{_RUTA_CLIENTES}/{cliente_b}", headers=headers)


async def test_propietario_tipo_y_rut_inmutables(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA_PROPIETARIOS, headers=headers, json=_body_propietario())
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        for cambio in ({"tipo": "EMPRESA_EXTERNA"}, {"rut": "6.666.666-6"}):
            resp = client.patch(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers, json=cambio)
            assert resp.status_code == 400, cambio
            assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers)


async def test_propietario_transiciones_y_null(session_factory) -> None:
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA_PROPIETARIOS, headers=headers, json=_body_propietario())
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        # Misma transición → 409 con los otros 2 estados
        resp = client.patch(f"{_RUTA_PROPIETARIOS}/{rid}/estado", headers=headers, json={"estado": "ACTIVO"})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == ["INACTIVO", "BLOQUEADO"]
        assert client.patch(
            f"{_RUTA_PROPIETARIOS}/{rid}/estado", headers=headers, json={"estado": "BLOQUEADO"}
        ).status_code == 200

        # Fuera del Literal → 422
        resp = client.patch(f"{_RUTA_PROPIETARIOS}/{rid}/estado", headers=headers, json={"estado": "SUSPENDIDO"})
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # `null` = sin cambio
        resp = client.patch(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers, json={"razon_social": None})
        assert resp.status_code == 400
        resp = client.patch(
            f"{_RUTA_PROPIETARIOS}/{rid}",
            headers=headers,
            json={"razon_social": None, "es_institucional_agas": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["es_institucional_agas"] is True

        client.delete(f"{_RUTA_PROPIETARIOS}/{rid}", headers=headers)


async def test_propietario_delete_con_referencias_409(session_factory) -> None:
    """Con un cilindro que lo referencia → 409; sin él → 204."""
    user, clave = await _admin_maestros(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(_RUTA_PROPIETARIOS, headers=headers, json=_body_propietario())
        assert resp.status_code == 201, resp.text
        propietario_id = resp.json()["id"]

    p = prefijo()
    async with session_factory() as session:
        tipo_gas = TipoGas(codigo=f"TG{p[:10]}", nombre="Gas de prueba 4.1")
        ubicacion = Ubicacion(codigo=f"UB{p[:10]}", nombre="Bodega 4.1", tipo="INTERNA")
        session.add_all([tipo_gas, ubicacion])
        await session.flush()
        cilindro = Cilindro(
            codigo_interno=f"CI{p[:10]}",
            numero_serie=f"NS{p[:10]}",
            codigo_qr=f"QR{p[:10]}",
            propietario_id=uuid.UUID(propietario_id),
            tipo_gas_id=tipo_gas.id,
            capacidad_kg=42,
            ubicacion_actual_id=ubicacion.id,
        )
        session.add(cilindro)
        await session.commit()
        cilindro_id = cilindro.id

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.delete(f"{_RUTA_PROPIETARIOS}/{propietario_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"

    async with session_factory() as session:
        cilindro = await session.get(Cilindro, cilindro_id)
        assert cilindro is not None
        await session.delete(cilindro)
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.delete(f"{_RUTA_PROPIETARIOS}/{propietario_id}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA_PROPIETARIOS}/{propietario_id}", headers=headers).status_code == 404
