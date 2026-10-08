"""
Tests del módulo de sesiones (subetapa 2.1): listado paginado con filtros
por usuario y estado, detalle y revocación idempotente que invalida el
refresh token de inmediato.
"""

from __future__ import annotations

import uuid

from factories import (
    TAREA_CATALOGOS,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    crear_usuario,
    login,
    token_de,
)
from fastapi.testclient import TestClient

from app.main import app

_RUTA = "/api/v1/sesiones"
_PERMISOS_SESIONES = ["PERM_01", "PERM_07"]


async def _admin_sesiones(session_factory):
    return await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_SESIONES
    )


# ============================================================
# GUARDS RBAC
# ============================================================


async def test_sesiones_sin_token_y_sin_dominio(session_factory) -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
    assert resp.status_code == 401
    assert codigo_error(resp) == "UNAUTHORIZED"

    # TAREA_29 (catálogos) no da acceso a las sesiones de usuarios.
    catalogos, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS_SESIONES
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, catalogos, clave))
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"
        assert TAREA_USUARIOS in resp.json()["detail"]["message"]

        resp = client.delete(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 403


# ============================================================
# LISTADO Y DETALLE
# ============================================================


async def test_listar_sesiones_con_filtros(session_factory) -> None:
    objetivo, clave_objetivo = await crear_usuario(session_factory)
    admin, clave_admin = await _admin_sesiones(session_factory)
    with TestClient(app) as client:
        # el objetivo genera su propia sesión
        assert login(client, objetivo.username, clave_objetivo).status_code == 200
        headers = cabecera(token_de(client, admin, clave_admin))

        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert set(cuerpo) == {"items", "total", "pagina", "por_pagina", "paginas"}
        assert cuerpo["total"] >= 1
        assert all("usuario_username" in i for i in cuerpo["items"])

        # filtro por usuario: solo sesiones del objetivo, con su username
        resp = client.get(_RUTA, headers=headers, params={"usuario_id": str(objetivo.id)})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items
        assert all(i["usuario_id"] == str(objetivo.id) for i in items)
        assert all(i["usuario_username"] == objetivo.username for i in items)
        assert all(i["revocada"] is False for i in items)

        # filtro de activas sin revocadas
        resp = client.get(_RUTA, headers=headers, params={"activas": "true"})
        assert resp.status_code == 200
        assert all(i["revocada"] is False for i in resp.json()["items"])

        # paginación mínima
        resp = client.get(_RUTA, headers=headers, params={"por_pagina": 1})
        assert len(resp.json()["items"]) == 1
        assert resp.json()["por_pagina"] == 1


async def test_detalle_sesion(session_factory) -> None:
    objetivo, clave = await crear_usuario(session_factory)
    admin, clave_admin = await _admin_sesiones(session_factory)
    with TestClient(app) as client:
        login(client, objetivo.username, clave)
        headers = cabecera(token_de(client, admin, clave_admin))

        resp = client.get(_RUTA, headers=headers, params={"usuario_id": str(objetivo.id)})
        sesion_id = resp.json()["items"][0]["id"]

        resp = client.get(f"{_RUTA}/{sesion_id}", headers=headers)
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert cuerpo["usuario_username"] == objetivo.username
        assert cuerpo["revocada"] is False
        # ip viene de columnas INET: normalizada a str (o null)
        assert cuerpo["ip_inicio"] is None or isinstance(cuerpo["ip_inicio"], str)

        resp = client.get(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        resp = client.get(f"{_RUTA}/no-uuid", headers=headers)
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_filtro_de_activas_e_inactivas(session_factory) -> None:
    objetivo, clave = await crear_usuario(session_factory)
    admin, clave_admin = await _admin_sesiones(session_factory)
    with TestClient(app) as client:
        headers_admin = cabecera(token_de(client, admin, clave_admin))
        login(client, objetivo.username, clave)

        resp = client.get(
            _RUTA, headers=headers_admin, params={"usuario_id": str(objetivo.id)}
        )
        sesion_id = resp.json()["items"][0]["id"]

        # viva: aparece en 'activas' y no en 'inactivas'
        resp = client.get(
            _RUTA,
            headers=headers_admin,
            params={"usuario_id": str(objetivo.id), "activas": "true"},
        )
        assert [i["id"] for i in resp.json()["items"]] == [sesion_id]
        resp = client.get(
            _RUTA,
            headers=headers_admin,
            params={"usuario_id": str(objetivo.id), "activas": "false"},
        )
        assert resp.json()["items"] == []

        # revocada: se invierte
        assert (
            client.delete(f"{_RUTA}/{sesion_id}", headers=headers_admin).status_code == 200
        )
        resp = client.get(
            _RUTA,
            headers=headers_admin,
            params={"usuario_id": str(objetivo.id), "activas": "true"},
        )
        assert resp.json()["items"] == []
        resp = client.get(
            _RUTA,
            headers=headers_admin,
            params={"usuario_id": str(objetivo.id), "activas": "false"},
        )
        items = resp.json()["items"]
        assert [i["id"] for i in items] == [sesion_id]
        assert items[0]["revocada"] is True


# ============================================================
# REVOCACIÓN
# ============================================================


async def test_revocar_sesion_invalida_el_refresh(session_factory) -> None:
    objetivo, clave = await crear_usuario(session_factory)
    admin, clave_admin = await _admin_sesiones(session_factory)
    with TestClient(app) as client:
        headers_admin = cabecera(token_de(client, admin, clave_admin))

        # sesión viva: el refresh rota sin problemas
        refresh_v1 = login(client, objetivo.username, clave).json()["refresh_token"]
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_v1})
        assert resp.status_code == 200
        refresh_v2 = resp.json()["refresh_token"]

        resp = client.get(_RUTA, headers=headers_admin, params={"usuario_id": str(objetivo.id)})
        sesion_id = resp.json()["items"][0]["id"]

        # el admin la revoca
        resp = client.delete(f"{_RUTA}/{sesion_id}", headers=headers_admin)
        assert resp.status_code == 200
        assert resp.json()["revocada"] is True
        assert resp.json()["revocada_por"] == str(admin.id)

        # el refresh más reciente ya no sirve
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_v2})
        assert resp.status_code == 401

        # revocar de nuevo es idempotente (200, sigue revocada)
        resp = client.delete(f"{_RUTA}/{sesion_id}", headers=headers_admin)
        assert resp.status_code == 200
        assert resp.json()["revocada"] is True

        # el detalle refleja el estado final
        resp = client.get(f"{_RUTA}/{sesion_id}", headers=headers_admin)
        assert resp.status_code == 200
        assert resp.json()["revocada"] is True


async def test_revocar_sesion_inexistente(session_factory) -> None:
    admin, clave = await _admin_sesiones(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, clave))
        resp = client.delete(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"
