"""
Tests de los módulos de tareas y permisos (subetapa 2.1): CRUD de catálogos
bajo TAREA_29, administración de la matriz `tarea_permiso` y borrado
condicionado a historial (409 HAS_HISTORY).
"""

from __future__ import annotations

import uuid

from factories import (
    TAREA_CATALOGOS,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    crear_empleado,
    token_de,
)
from fastapi.testclient import TestClient

from app.main import app
from app.models import EmpleadoTarea

_RUTA_TAREAS = "/api/v1/tareas"
_RUTA_PERMISOS = "/api/v1/permisos"
_PERMISOS_CATALOGO = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]


async def _catalogos(session_factory):
    return await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS_CATALOGO
    )


def _codigo_unico() -> str:
    return f"T{uuid.uuid4().hex[:10]}"


# ============================================================
# GUARDS RBAC
# ============================================================


async def test_catalogos_sin_token_y_sin_dominio(session_factory) -> None:
    with TestClient(app) as client:
        assert client.get(_RUTA_TAREAS).status_code == 401
        assert client.get(_RUTA_PERMISOS).status_code == 401

    # TAREA_28 administra personas, no catálogos.
    persona, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_CATALOGO
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, persona, clave))
        resp = client.get(_RUTA_TAREAS, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"
        assert TAREA_CATALOGOS in resp.json()["detail"]["message"]

        assert client.get(_RUTA_PERMISOS, headers=headers).status_code == 403
        assert client.post(_RUTA_TAREAS, headers=headers, json={}).status_code == 403


# ============================================================
# CRUD DE TAREAS
# ============================================================


async def test_crud_tarea_completo(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    codigo = _codigo_unico()
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={
                "codigo": codigo,
                "nombre": "Llenar cilindro 10kg",
                "categoria": "OPERATIVO",
                "descripcion": "Tarea de prueba",
            },
        )
        assert resp.status_code == 201
        creado = resp.json()
        assert creado["estado"] == "ACTIVA"
        assert creado["es_operativa"] is True

        # duplicado → 409
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": codigo, "nombre": "Otra", "categoria": "OPERATIVO"},
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # categoría fuera de ck_tarea_categoria → 422
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": _codigo_unico(), "nombre": "X", "categoria": "INVENTADA"},
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # listado con filtros
        resp = client.get(
            _RUTA_TAREAS, headers=headers, params={"categoria": "OPERATIVO", "q": codigo}
        )
        assert resp.status_code == 200
        assert [i["id"] for i in resp.json()["items"]] == [creado["id"]]

        resp = client.get(_RUTA_TAREAS, headers=headers, params={"estado": "ACTIVA", "q": codigo})
        assert resp.json()["items"]

        # detalle
        resp = client.get(f"{_RUTA_TAREAS}/{creado['id']}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["codigo"] == codigo

        # actualización parcial
        resp = client.patch(
            f"{_RUTA_TAREAS}/{creado['id']}", headers=headers, json={"nombre": "Llenado 10kg v2"}
        )
        assert resp.status_code == 200
        assert resp.json()["nombre"] == "Llenado 10kg v2"

        resp = client.patch(f"{_RUTA_TAREAS}/{creado['id']}", headers=headers, json={})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_transiciones_de_estado_tarea(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    codigo = _codigo_unico()
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": codigo, "nombre": "Tarea estado", "categoria": "CALIDAD"},
        )
        tarea_id = resp.json()["id"]

        resp = client.patch(
            f"{_RUTA_TAREAS}/{tarea_id}/estado", headers=headers, json={"estado": "INACTIVA"}
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "INACTIVA"

        resp = client.patch(
            f"{_RUTA_TAREAS}/{tarea_id}/estado", headers=headers, json={"estado": "INACTIVA"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"

        resp = client.patch(
            f"{_RUTA_TAREAS}/{tarea_id}/estado", headers=headers, json={"estado": "DESHABILITADA"}
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_eliminar_tarea_sin_referencias(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    codigo = _codigo_unico()
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": codigo, "nombre": "Borrable", "categoria": "MAESTROS"},
        )
        tarea_id = resp.json()["id"]

        resp = client.delete(f"{_RUTA_TAREAS}/{tarea_id}", headers=headers)
        assert resp.status_code == 204

        resp = client.get(f"{_RUTA_TAREAS}/{tarea_id}", headers=headers)
        assert resp.status_code == 404

        resp = client.delete(f"{_RUTA_TAREAS}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404


async def test_eliminar_tarea_con_historial_devuelve_409(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    codigo = _codigo_unico()
    empleado, _ = await crear_empleado(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": codigo, "nombre": "Con historial", "categoria": "DESPACHO"},
        )
        tarea_id = resp.json()["id"]

    # historial de asignación (insert directo: el guard de personas no es parte de este test)
    async with session_factory() as session:
        session.add(
            EmpleadoTarea(
                empleado_id=empleado.id,
                tarea_id=uuid.UUID(tarea_id),
                usuario_asigno_id=admin.id,
            )
        )
        await session.commit()

    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.delete(f"{_RUTA_TAREAS}/{tarea_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"
        assert codigo in resp.json()["detail"]["message"]

        # la alternativa documentada sí funciona: inactivar la tarea
        resp = client.patch(
            f"{_RUTA_TAREAS}/{tarea_id}/estado", headers=headers, json={"estado": "INACTIVA"}
        )
        assert resp.status_code == 200


# ============================================================
# MATRIZ TAREA ↔ PERMISO
# ============================================================


async def test_matriz_de_permisos_de_tarea(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        # tarea y permiso únicos para aislar la matriz
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": _codigo_unico(), "nombre": "T matriz", "categoria": "AUDITORIA"},
        )
        tarea_id = resp.json()["id"]
        resp = client.post(
            _RUTA_PERMISOS,
            headers=headers,
            json={"codigo": f"P{uuid.uuid4().hex[:10]}", "nombre": "Permiso matriz"},
        )
        assert resp.status_code == 201
        permiso_id = resp.json()["id"]

        # lista vacía al inicio
        resp = client.get(f"{_RUTA_TAREAS}/{tarea_id}/permisos", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == []

        # conceder
        resp = client.post(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos",
            headers=headers,
            json={"permiso_id": permiso_id},
        )
        assert resp.status_code == 201
        assert resp.json()["concedido"] is True
        assert resp.json()["permiso_codigo"]

        # la lista ya lo incluye
        resp = client.get(f"{_RUTA_TAREAS}/{tarea_id}/permisos", headers=headers)
        assert [i["permiso_id"] for i in resp.json()] == [permiso_id]

        # duplicado → 409
        resp = client.post(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos",
            headers=headers,
            json={"permiso_id": permiso_id},
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # permiso o tarea inexistentes → 404
        resp = client.post(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos",
            headers=headers,
            json={"permiso_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

        resp = client.get(f"{_RUTA_TAREAS}/{uuid.uuid4()}/permisos", headers=headers)
        assert resp.status_code == 404

        # quitar → 204 y vuelve a vacío
        resp = client.delete(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos/{permiso_id}", headers=headers
        )
        assert resp.status_code == 204

        resp = client.get(f"{_RUTA_TAREAS}/{tarea_id}/permisos", headers=headers)
        assert resp.json() == []

        resp = client.delete(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos/{permiso_id}", headers=headers
        )
        assert resp.status_code == 404


# ============================================================
# CRUD DE PERMISOS
# ============================================================


async def test_crud_permiso_completo(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    codigo = f"P{uuid.uuid4().hex[:10]}"
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        resp = client.post(
            _RUTA_PERMISOS,
            headers=headers,
            json={"codigo": codigo, "nombre": "Exportar reportes", "es_critico": True},
        )
        assert resp.status_code == 201
        creado = resp.json()
        assert creado["es_critico"] is True

        # duplicado → 409
        resp = client.post(
            _RUTA_PERMISOS, headers=headers, json={"codigo": codigo, "nombre": "Otro"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # código demasiado largo → 422
        resp = client.post(
            _RUTA_PERMISOS, headers=headers, json={"codigo": "X" * 31, "nombre": "Largo"}
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # listado con q
        resp = client.get(_RUTA_PERMISOS, headers=headers, params={"q": codigo})
        assert [i["id"] for i in resp.json()["items"]] == [creado["id"]]

        # listado por crítico
        resp = client.get(
            _RUTA_PERMISOS, headers=headers, params={"q": codigo, "es_critico": "true"}
        )
        assert resp.json()["total"] == 1

        # detalle
        resp = client.get(f"{_RUTA_PERMISOS}/{creado['id']}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["codigo"] == codigo

        # actualización (el código es inmutable: no está en el esquema)
        resp = client.patch(
            f"{_RUTA_PERMISOS}/{creado['id']}",
            headers=headers,
            json={"nombre": "Exportar (v2)", "es_critico": False},
        )
        assert resp.status_code == 200
        assert resp.json()["nombre"] == "Exportar (v2)"
        assert resp.json()["codigo"] == codigo

        resp = client.patch(f"{_RUTA_PERMISOS}/{creado['id']}", headers=headers, json={})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.get(f"{_RUTA_PERMISOS}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404


async def test_eliminar_permiso_seguro_y_con_matriz(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))

        # permiso sin matriz → borrado directo
        resp = client.post(
            _RUTA_PERMISOS,
            headers=headers,
            json={"codigo": f"P{uuid.uuid4().hex[:10]}", "nombre": "Libre"},
        )
        libre_id = resp.json()["id"]
        resp = client.delete(f"{_RUTA_PERMISOS}/{libre_id}", headers=headers)
        assert resp.status_code == 204
        assert client.get(f"{_RUTA_PERMISOS}/{libre_id}", headers=headers).status_code == 404

        # permiso concedido en una tarea → 409 HAS_HISTORY
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": _codigo_unico(), "nombre": "Poseedora", "categoria": "ADMIN"},
        )
        tarea_id = resp.json()["id"]
        resp = client.post(
            _RUTA_PERMISOS,
            headers=headers,
            json={"codigo": f"P{uuid.uuid4().hex[:10]}", "nombre": "Con matriz"},
        )
        con_matriz_id = resp.json()["id"]
        resp = client.post(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos",
            headers=headers,
            json={"permiso_id": con_matriz_id},
        )
        assert resp.status_code == 201

        resp = client.delete(f"{_RUTA_PERMISOS}/{con_matriz_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"

        # al quitarlo de la matriz, el borrado pasa
        resp = client.delete(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos/{con_matriz_id}", headers=headers
        )
        assert resp.status_code == 204
        resp = client.delete(f"{_RUTA_PERMISOS}/{con_matriz_id}", headers=headers)
        assert resp.status_code == 204


async def test_listar_tareas_paginacion(session_factory) -> None:
    admin, clave = await _catalogos(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.get(_RUTA_TAREAS, headers=headers, params={"por_pagina": 1, "pagina": 1})
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert set(cuerpo) == {"items", "total", "pagina", "por_pagina", "paginas"}
        assert len(cuerpo["items"]) == 1
        assert cuerpo["por_pagina"] == 1


async def test_verificar_unico_excluye_registro_propio(session_factory) -> None:
    """Sanidad del helper: un PATCH con el propio username no choca (409 falso)."""
    usuario, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=["PERM_01", "PERM_03"]
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, usuario, clave))
        resp = client.patch(
            f"/api/v1/usuarios/{usuario.id}", headers=headers, json={"username": usuario.username}
        )
        assert resp.status_code == 200


async def test_conteo_de_referencias_protege_tarea_de_matrices(session_factory) -> None:
    """Una tarea con solo matriz (sin asignaciones) también rechaza el DELETE."""
    admin, clave = await _catalogos(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.post(
            _RUTA_TAREAS,
            headers=headers,
            json={"codigo": _codigo_unico(), "nombre": "Solo matriz", "categoria": "REPORTES"},
        )
        tarea_id = resp.json()["id"]
        resp = client.post(
            _RUTA_PERMISOS,
            headers=headers,
            json={"codigo": f"P{uuid.uuid4().hex[:10]}", "nombre": "Para matriz"},
        )
        permiso_id = resp.json()["id"]
        resp = client.post(
            f"{_RUTA_TAREAS}/{tarea_id}/permisos",
            headers=headers,
            json={"permiso_id": permiso_id},
        )
        assert resp.status_code == 201

        resp = client.delete(f"{_RUTA_TAREAS}/{tarea_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"
