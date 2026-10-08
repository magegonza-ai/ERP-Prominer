"""
Tests del módulo de auditoría (subetapa 2.1): SOLO LECTURA bajo TAREA_30.

La BD de pruebas se crea con `Base.metadata.create_all` (sin los triggers de
la migración 0002), así que estos tests insertan filas de forma directa con
valores controlados y luego validan filtros, paginación y detalle vía API.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from factories import (
    TAREA_AUDITORIA,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    token_de,
)
from fastapi.testclient import TestClient

from app.main import app
from app.models import Auditoria

_RUTA = "/api/v1/auditoria"


async def _auditor(session_factory):
    return await crear_cadena_rbac(
        session_factory, tareas=[TAREA_AUDITORIA], permisos=["PERM_01"]
    )


async def _insertar_registro(session_factory, *, modulo: str, **campos) -> Auditoria:
    datos = {
        "modulo": modulo,
        "accion": "INSERT",
        "registro_tipo": "usuario",
        "valor_nuevo": {"username": "auditoria_prueba"},
        "ip": "127.0.0.1",
        "user_agent": "pytest",
    }
    datos.update(campos)
    async with session_factory() as session:
        registro = Auditoria(**datos)
        session.add(registro)
        await session.commit()
        await session.refresh(registro)
    return registro


# ============================================================
# GUARDS RBAC
# ============================================================


async def test_auditoria_sin_token_y_sin_tarea(session_factory) -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
    assert resp.status_code == 401
    assert codigo_error(resp) == "UNAUTHORIZED"

    # TAREA_28 (administrar usuarios) NO incluye revisar la auditoría.
    usuarios_admin, clave = await crear_cadena_rbac(
        session_factory,
        tareas=[TAREA_USUARIOS],
        permisos=["PERM_01", "PERM_02", "PERM_03", "PERM_07"],
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, usuarios_admin, clave))
        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"
        assert TAREA_AUDITORIA in resp.json()["detail"]["message"]


async def test_auditoria_no_expone_escritura(session_factory) -> None:
    auditor, clave = await _auditor(session_factory)
    with TestClient(app) as client:
        headers = cabecera(token_de(client, auditor, clave))
        assert client.post(_RUTA, headers=headers, json={}).status_code == 405
        assert client.patch(_RUTA, headers=headers, json={}).status_code == 405
        assert client.delete(_RUTA, headers=headers).status_code == 405

        # y el esquema OpenAPI tampoco declara métodos de escritura
        rutas = client.get("/openapi.json").json()["paths"]
        assert set(rutas[_RUTA]) == {"get"}


# ============================================================
# LISTADO Y FILTROS
# ============================================================


async def test_listar_auditoria_paginada_y_filtrada(session_factory) -> None:
    auditor, clave = await _auditor(session_factory)
    modulo = f"pruebas_{uuid.uuid4().hex[:8]}"
    registro = await _insertar_registro(session_factory, modulo=modulo, usuario_id=auditor.id)
    ahora = datetime.now(UTC)

    with TestClient(app) as client:
        headers = cabecera(token_de(client, auditor, clave))

        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert set(cuerpo) == {"items", "total", "pagina", "por_pagina", "paginas"}
        assert cuerpo["total"] >= 1
        assert all("valor_nuevo" in i for i in cuerpo["items"])

        # por módulo (aislado: solo este test usa este módulo)
        resp = client.get(_RUTA, headers=headers, params={"modulo": modulo})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == str(registro.id)

        # por acción y tipo de registro
        resp = client.get(
            _RUTA, headers=headers, params={"modulo": modulo, "accion": "INSERT"}
        )
        assert resp.json()["total"] == 1
        resp = client.get(
            _RUTA, headers=headers, params={"modulo": modulo, "accion": "DELETE"}
        )
        assert resp.json()["total"] == 0
        resp = client.get(
            _RUTA, headers=headers, params={"modulo": modulo, "registro_tipo": "usuario"}
        )
        assert resp.json()["total"] == 1

        # por usuario
        resp = client.get(
            _RUTA, headers=headers, params={"modulo": modulo, "usuario_id": str(auditor.id)}
        )
        assert resp.json()["total"] == 1

        # rango de fechas inclusivo
        resp = client.get(
            _RUTA,
            headers=headers,
            params={
                "modulo": modulo,
                "fecha_desde": (ahora - timedelta(days=1)).isoformat(),
                "fecha_hasta": (ahora + timedelta(days=1)).isoformat(),
            },
        )
        assert resp.json()["total"] == 1

        resp = client.get(
            _RUTA,
            headers=headers,
            params={"modulo": modulo, "fecha_desde": (ahora + timedelta(days=1)).isoformat()},
        )
        assert resp.json()["total"] == 0

        # sin resultados → página vacía con metadatos coherentes
        resp = client.get(_RUTA, headers=headers, params={"modulo": "inexistente_xyz"})
        assert resp.status_code == 200
        assert resp.json() == {
            "items": [],
            "total": 0,
            "pagina": 1,
            "por_pagina": 20,
            "paginas": 1,
        }


async def test_auditoria_paginacion(session_factory) -> None:
    auditor, clave = await _auditor(session_factory)
    modulo = f"pruebas_{uuid.uuid4().hex[:8]}"
    await _insertar_registro(session_factory, modulo=modulo)
    await _insertar_registro(session_factory, modulo=modulo)

    with TestClient(app) as client:
        headers = cabecera(token_de(client, auditor, clave))
        resp = client.get(
            _RUTA, headers=headers, params={"modulo": modulo, "por_pagina": 1}
        )
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert cuerpo["total"] == 2
        assert cuerpo["paginas"] == 2
        assert len(cuerpo["items"]) == 1
        assert cuerpo["por_pagina"] == 1


# ============================================================
# DETALLE
# ============================================================


async def test_detalle_de_registro(session_factory) -> None:
    auditor, clave = await _auditor(session_factory)
    modulo = f"pruebas_{uuid.uuid4().hex[:8]}"
    registro = await _insertar_registro(
        session_factory,
        modulo=modulo,
        usuario_id=auditor.id,
        motivo="Alta de usuario de prueba",
        valor_anterior={"email": "anterior@agas.test"},
    )

    with TestClient(app) as client:
        headers = cabecera(token_de(client, auditor, clave))

        resp = client.get(f"{_RUTA}/{registro.id}", headers=headers)
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert cuerpo["modulo"] == modulo
        assert cuerpo["accion"] == "INSERT"
        assert cuerpo["usuario_id"] == str(auditor.id)
        assert cuerpo["motivo"] == "Alta de usuario de prueba"
        assert cuerpo["valor_anterior"] == {"email": "anterior@agas.test"}
        assert cuerpo["valor_nuevo"] == {"username": "auditoria_prueba"}
        assert cuerpo["ip"] == "127.0.0.1"

        resp = client.get(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        resp = client.get(f"{_RUTA}/no-uuid", headers=headers)
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"
