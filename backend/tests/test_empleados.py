"""
Tests del módulo de empleados (subetapa 2.1): CRUD con validaciones de
unicidad y FK, transiciones del ciclo ck_empleado_estado, baja lógica con
revocación de asignaciones y asignación/revocación de tareas (PERM_09/10).
"""

from __future__ import annotations

import uuid
from datetime import date

from factories import (
    CLAVE,
    TAREA_CATALOGOS,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    crear_empleado,
    crear_tarea_unica,
    obtener_o_crear_area,
    token_de,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import EmpleadoTarea

_RUTA = "/api/v1/empleados"
# TAREA_28 con todas las acciones de personas, incluidas asignar/reasignar.
_PERMISOS_PERSONAS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07", "PERM_09", "PERM_10"]


async def _admin_personas(session_factory):
    return await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_PERSONAS
    )


async def _cuerpo_empleado(session_factory, **extras) -> dict:
    async with session_factory() as session:
        area = await obtener_o_crear_area(session)
    p = uuid.uuid4().hex[:10]
    cuerpo = {
        "rut": f"9{p[:8]}",
        "nombres": "Nueva",
        "apellidos": f"Persona {p[:6]}",
        "cargo": "Operador",
        "area_id": str(area.id),
        "correo": f"emp_{p}@agas.test",
        "fecha_ingreso": "2026-02-01",
    }
    cuerpo.update(extras)
    return cuerpo


# ============================================================
# GUARDS RBAC
# ============================================================


async def test_empleados_sin_token_y_sin_dominio(session_factory) -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
    assert resp.status_code == 401
    assert codigo_error(resp) == "UNAUTHORIZED"

    usuario, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS_PERSONAS
    )
    with TestClient(app) as client:
        token = token_de(client, usuario, clave)
        resp = client.get(_RUTA, headers=cabecera(token))
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"

        resp = client.post(_RUTA, headers=cabecera(token), json={})
        assert resp.status_code == 403


# ============================================================
# CRUD
# ============================================================


async def test_crud_empleado_completo(session_factory) -> None:
    admin, clave = await _admin_personas(session_factory)
    cuerpo = await _cuerpo_empleado(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.post(_RUTA, headers=headers, json=cuerpo)
        assert resp.status_code == 201
        creado = resp.json()
        assert creado["estado"] == "ACTIVO"
        assert creado["rut"] == cuerpo["rut"]

        # listado con búsqueda por RUT y filtro de estado
        resp = client.get(_RUTA, headers=headers, params={"q": cuerpo["rut"], "estado": "ACTIVO"})
        assert resp.status_code == 200
        assert [i["id"] for i in resp.json()["items"]] == [creado["id"]]

        # listado filtrado por área (combinado con RUT: la área es compartida)
        resp = client.get(
            _RUTA,
            headers=headers,
            params={"area_id": cuerpo["area_id"], "q": cuerpo["rut"]},
        )
        assert resp.status_code == 200
        assert [i["id"] for i in resp.json()["items"]] == [creado["id"]]

        # detalle
        resp = client.get(f"{_RUTA}/{creado['id']}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["correo"] == cuerpo["correo"]

        # actualización parcial
        resp = client.patch(
            f"{_RUTA}/{creado['id']}",
            headers=headers,
            json={"cargo": "Supervisor", "telefono": "+56912345678"},
        )
        assert resp.status_code == 200
        assert resp.json()["cargo"] == "Supervisor"
        assert resp.json()["telefono"] == "+56912345678"

        resp = client.get(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_crear_empleado_validaciones(session_factory) -> None:
    existente, _ = await crear_empleado(session_factory)
    admin, clave = await _admin_personas(session_factory)
    cuerpo = await _cuerpo_empleado(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.post(
            _RUTA, headers=headers, json={**cuerpo, "area_id": str(uuid.uuid4())}
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        resp = client.post(_RUTA, headers=headers, json={**cuerpo, "rut": existente.rut})
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        resp = client.post(_RUTA, headers=headers, json={**cuerpo, "correo": existente.correo})
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        resp = client.post(_RUTA, headers=headers, json={**cuerpo, "rut": "123"})
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.post(_RUTA, headers=headers, json={**cuerpo, "correo": "no-es-correo"})
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_actualizar_empleado_validaciones(session_factory) -> None:
    propio, _ = await crear_empleado(session_factory)
    otro, _ = await crear_empleado(session_factory)
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.patch(f"{_RUTA}/{propio.id}", headers=headers, json={})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.patch(f"{_RUTA}/{propio.id}", headers=headers, json={"correo": otro.correo})
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # conservar el propio correo → 200 (excluye el propio registro)
        resp = client.patch(f"{_RUTA}/{propio.id}", headers=headers, json={"correo": propio.correo})
        assert resp.status_code == 200

        resp = client.patch(
            f"{_RUTA}/{propio.id}", headers=headers, json={"area_id": str(uuid.uuid4())}
        )
        assert resp.status_code == 404


# ============================================================
# ESTADOS Y BAJA LÓGICA
# ============================================================


async def test_transiciones_de_estado_laboral(session_factory) -> None:
    empleado, _ = await crear_empleado(session_factory)
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.patch(
            f"{_RUTA}/{empleado.id}/estado", headers=headers, json={"estado": "LICENCIA"}
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "LICENCIA"

        # mismo estado → 409 con los destinos posibles
        resp = client.patch(
            f"{_RUTA}/{empleado.id}/estado", headers=headers, json={"estado": "LICENCIA"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert "RETIRADO" in resp.json()["detail"]["extra"]["allowed_states"]

        # estado fuera del ciclo → 422
        resp = client.patch(
            f"{_RUTA}/{empleado.id}/estado", headers=headers, json={"estado": "CESADO"}
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # volver a ACTIVO
        resp = client.patch(
            f"{_RUTA}/{empleado.id}/estado", headers=headers, json={"estado": "ACTIVO"}
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "ACTIVO"

        # ACTIVO → RETIRADO vía endpoint de estado (revoca asignaciones VIGENTES)
        resp = client.patch(
            f"{_RUTA}/{empleado.id}/estado", headers=headers, json={"estado": "RETIRADO"}
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "RETIRADO"


async def test_parchear_empleado_con_null_no_modifica(session_factory) -> None:
    empleado, _ = await crear_empleado(session_factory)
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.patch(f"{_RUTA}/{empleado.id}", headers=headers, json={"correo": None})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.patch(
            f"{_RUTA}/{empleado.id}",
            headers=headers,
            json={"correo": None, "cargo": "Mecánico"},
        )
        assert resp.status_code == 200
        assert resp.json()["correo"] == empleado.correo
        assert resp.json()["cargo"] == "Mecánico"


async def test_baja_logica_revoca_asignaciones_vigentes(session_factory) -> None:
    empleado, _ = await crear_empleado(session_factory)
    tarea = await crear_tarea_unica(session_factory)
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.post(
            f"{_RUTA}/{empleado.id}/tareas", headers=headers, json={"tarea_id": str(tarea.id)}
        )
        assert resp.status_code == 201

        resp = client.delete(f"{_RUTA}/{empleado.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["estado"] == "RETIRADO"

    async with session_factory() as session:
        asignaciones = (
            await session.execute(
                select(EmpleadoTarea).where(EmpleadoTarea.empleado_id == empleado.id)
            )
        ).scalars().all()
    assert asignaciones
    assert all(a.estado == "REVOCADA" for a in asignaciones)
    assert all(a.fecha_termino == date.today() for a in asignaciones)


# ============================================================
# ASIGNACIÓN DE TAREAS
# ============================================================


async def test_asignar_revocar_y_listar_tareas(session_factory) -> None:
    empleado, _ = await crear_empleado(session_factory)
    tarea = await crear_tarea_unica(session_factory)
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.post(
            f"{_RUTA}/{empleado.id}/tareas",
            headers=headers,
            json={"tarea_id": str(tarea.id), "observaciones": "Turno mañana"},
        )
        assert resp.status_code == 201
        asignacion = resp.json()
        assert asignacion["estado"] == "VIGENTE"
        assert asignacion["usuario_asigno_id"] == str(admin.id)

        resp = client.get(f"{_RUTA}/{empleado.id}/tareas", headers=headers)
        assert resp.status_code == 200
        assert [a["id"] for a in resp.json()] == [asignacion["id"]]

        # revocar la asignación VIGENTE
        resp = client.delete(
            f"{_RUTA}/{empleado.id}/tareas/{tarea.id}", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "REVOCADA"
        assert resp.json()["fecha_termino"] == date.today().isoformat()

        # sin VIGENTE → 404
        resp = client.delete(f"{_RUTA}/{empleado.id}/tareas/{tarea.id}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        # el filtro por estado queda vacío para VIGENTE
        resp = client.get(
            f"{_RUTA}/{empleado.id}/tareas", headers=headers, params={"estado": "VIGENTE"}
        )
        assert resp.status_code == 200
        assert resp.json() == []


async def test_asignar_tarea_validaciones(session_factory) -> None:
    empleado, _ = await crear_empleado(session_factory)
    tarea = await crear_tarea_unica(session_factory)
    retirado, _ = await crear_empleado(session_factory, estado="RETIRADO")
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        # empleado no ACTIVO → 403 EMPLOYEE_INACTIVE
        resp = client.post(
            f"{_RUTA}/{retirado.id}/tareas", headers=headers, json={"tarea_id": str(tarea.id)}
        )
        assert resp.status_code == 403
        assert codigo_error(resp) == "EMPLOYEE_INACTIVE"

        # empleado inexistente → 404
        resp = client.post(
            f"{_RUTA}/{uuid.uuid4()}/tareas", headers=headers, json={"tarea_id": str(tarea.id)}
        )
        assert resp.status_code == 404

        # tarea inexistente → 404
        resp = client.post(
            f"{_RUTA}/{empleado.id}/tareas", headers=headers, json={"tarea_id": str(uuid.uuid4())}
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        # fechas invertidas → 400
        resp = client.post(
            f"{_RUTA}/{empleado.id}/tareas",
            headers=headers,
            json={"tarea_id": str(tarea.id), "fecha_inicio": "2026-03-10", "fecha_termino": "2026-03-01"},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # asignación válida y luego duplicada → 409
        resp = client.post(
            f"{_RUTA}/{empleado.id}/tareas", headers=headers, json={"tarea_id": str(tarea.id)}
        )
        assert resp.status_code == 201

        resp = client.post(
            f"{_RUTA}/{empleado.id}/tareas", headers=headers, json={"tarea_id": str(tarea.id)}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


async def test_asignar_tarea_con_empleado_de_otro_dominio_es_prohibido(session_factory) -> None:
    """Un admin de catálogos (TAREA_29) no administra personas."""
    empleado, _ = await crear_empleado(session_factory)
    tarea = await crear_tarea_unica(session_factory)
    catalogos, clave = await crear_cadena_rbac(
        session_factory,
        tareas=[TAREA_CATALOGOS],
        permisos=["PERM_01", "PERM_02", "PERM_09"],
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, catalogos, clave))
        resp = client.post(
            f"{_RUTA}/{empleado.id}/tareas", headers=headers, json={"tarea_id": str(tarea.id)}
        )
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"

        resp = client.delete(
            f"{_RUTA}/{empleado.id}/tareas/{tarea.id}", headers=headers
        )
        assert resp.status_code == 403


async def test_asignaciones_de_empleado_inexistente(session_factory) -> None:
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.get(f"{_RUTA}/{uuid.uuid4()}/tareas", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_listar_empleados_sin_filtros_devuelve_pagina(session_factory) -> None:
    admin, clave = await _admin_personas(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.get(_RUTA, headers=headers, params={"por_pagina": 1})
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert set(cuerpo) == {"items", "total", "pagina", "por_pagina", "paginas"}
        assert len(cuerpo["items"]) == 1


async def test_crear_empleado_con_clave_de_auth_no_requiere(session_factory) -> None:
    """Smoke: CLAVE cumple la política para poder loguear admins creados."""
    admin, clave = await _admin_personas(session_factory)
    assert clave == CLAVE
    with TestClient(app) as client:
        assert token_de(client, admin, clave)
