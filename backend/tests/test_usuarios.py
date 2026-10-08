"""
Tests del módulo de usuarios (subetapa 2.1): guards RBAC (TAREA_28 +
acciones), listado paginado, alta con política de contraseña, actualización,
transiciones de estado, reseteo de contraseña y anulación lógica.
"""

from __future__ import annotations

import uuid

import pytest
from factories import (
    CLAVE,
    TAREA_CATALOGOS,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    crear_empleado,
    crear_usuario,
    login,
    token_de,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import RequireTaskPermission, verificar_unico
from app.core.exceptions import PermissionDenied
from app.main import app
from app.models import Sesion, Usuario

_RUTA = "/api/v1/usuarios"
_PERMISOS_USUARIOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]


# ============================================================
# GUARDS RBAC
# ============================================================


async def test_listar_usuarios_sin_token_devuelve_401() -> None:
    with TestClient(app) as client:
        resp = client.get(_RUTA)
    assert resp.status_code == 401
    assert codigo_error(resp) == "UNAUTHORIZED"


async def test_listar_usuarios_sin_tarea_de_dominio_devuelve_403(session_factory) -> None:
    """TAREA_29 administra catálogos, no usuarios: el dominio no cruza."""
    usuario, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        token = token_de(client, usuario, clave)
        resp = client.get(_RUTA, headers=cabecera(token))
    assert resp.status_code == 403
    assert codigo_error(resp) == "PERMISSION_DENIED"
    assert TAREA_USUARIOS in resp.json()["detail"]["message"]


async def test_crear_usuario_sin_tarea_de_dominio_devuelve_403(session_factory) -> None:
    usuario, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        token = token_de(client, usuario, clave)
        resp = client.post(
            _RUTA,
            headers=cabecera(token),
            json={"username": "x123", "email": "x123@agas.test", "password": CLAVE},
        )
    assert resp.status_code == 403
    assert codigo_error(resp) == "PERMISSION_DENIED"


async def test_require_task_permission_unitario(session_factory) -> None:
    """Falla sin la tarea (dominio) y sin el permiso (acción); pasa con ambos."""
    # Códigos únicos: la matriz es global por tarea, así cada tarea aísla su caso.
    tarea_sin_permiso = f"T{uuid.uuid4().hex[:10]}"
    tarea_con_permiso = f"T{uuid.uuid4().hex[:10]}"
    sin_tarea, _ = await crear_cadena_rbac(session_factory)
    con_tarea_sin_permiso, _ = await crear_cadena_rbac(
        session_factory, tareas=[tarea_sin_permiso]
    )
    con_todo, _ = await crear_cadena_rbac(
        session_factory, tareas=[tarea_con_permiso], permisos=["PERM_02"]
    )

    async with session_factory() as session:
        dependencia_sin_permiso = RequireTaskPermission(tarea_sin_permiso, "PERM_02")
        with pytest.raises(PermissionDenied):
            await dependencia_sin_permiso(user=sin_tarea, session=session)
        with pytest.raises(PermissionDenied):
            await dependencia_sin_permiso(user=con_tarea_sin_permiso, session=session)

        dependencia_ok = RequireTaskPermission(tarea_con_permiso, "PERM_02")
        assert await dependencia_ok(user=con_todo, session=session) is con_todo


# ============================================================
# LISTADO Y DETALLE
# ============================================================


async def test_listar_usuarios_paginado_y_filtros(session_factory) -> None:
    objetivo, clave = await crear_cadena_rbac(session_factory, estado="BLOQUEADO")
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        token = token_de(client, admin, admin_clave)
        headers = cabecera(token)

        resp = client.get(_RUTA, headers=headers)
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert set(cuerpo) == {"items", "total", "pagina", "por_pagina", "paginas"}
        assert cuerpo["total"] >= 1
        assert cuerpo["pagina"] == 1
        assert all("password_hash" not in i for i in cuerpo["items"])

        # el admin aparece al buscar por su username exacto
        resp = client.get(_RUTA, headers=headers, params={"q": admin.username})
        assert [i["username"] for i in resp.json()["items"]] == [admin.username]

        # filtros combinados: estado exacto + búsqueda por username
        resp = client.get(
            _RUTA, headers=headers, params={"estado": "BLOQUEADO", "q": objetivo.username}
        )
        assert resp.status_code == 200
        assert [i["username"] for i in resp.json()["items"]] == [objetivo.username]

        # paginación mínima
        resp = client.get(_RUTA, headers=headers, params={"por_pagina": 1, "pagina": 1})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["por_pagina"] == 1


async def test_detalle_usuario_y_404(session_factory) -> None:
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=["PERM_01"]
    )
    with TestClient(app) as client:
        token = token_de(client, admin, admin_clave)
        headers = cabecera(token)

        resp = client.get(f"{_RUTA}/{admin.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == admin.username
        assert "password_hash" not in resp.json()
        assert "totp_secret" not in resp.json()

        resp = client.get(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        resp = client.get(f"{_RUTA}/no-es-uuid", headers=headers)
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


# ============================================================
# ALTA
# ============================================================


async def test_crear_usuario_aplica_politica_y_defaults(session_factory) -> None:
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    p = uuid.uuid4().hex[:10]
    with TestClient(app) as client:
        token = token_de(client, admin, admin_clave)
        headers = cabecera(token)

        # contraseña débil → 400 con el detalle de la política
        resp = client.post(
            _RUTA,
            headers=headers,
            json={"username": f"debil_{p}", "email": f"debil_{p}@agas.test", "password": "abc"},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "PASSWORD_POLICY_ERROR"

        # alta válida → 201 con defaults de activación
        resp = client.post(
            _RUTA,
            headers=headers,
            json={
                "username": f"nuevo_{p}",
                "email": f"nuevo_{p}@agas.test",
                "password": CLAVE,
            },
        )
        assert resp.status_code == 201
        cuerpo = resp.json()
        assert cuerpo["estado"] == "PENDIENTE_ACTIVACION"
        assert cuerpo["requiere_cambio_password"] is True
        assert "password_hash" not in cuerpo

        # sin estado explícito → PENDIENTE_ACTIVACION no puede entrar todavía
        resp = login(client, f"nuevo_{p}", CLAVE)
        assert resp.status_code == 401
        assert codigo_error(resp) == "ACCOUNT_PENDING_ACTIVATION"

        # alta con estado ACTIVO → puede entrar de inmediato
        resp = client.post(
            _RUTA,
            headers=headers,
            json={
                "username": f"activo_{p}",
                "email": f"activo_{p}@agas.test",
                "password": CLAVE,
                "estado": "ACTIVO",
            },
        )
        assert resp.status_code == 201
        assert login(client, f"activo_{p}", CLAVE).status_code == 200


async def test_crear_usuario_duplicados_y_validaciones(session_factory) -> None:
    existente, _ = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    p = uuid.uuid4().hex[:10]
    with TestClient(app) as client:
        token = token_de(client, admin, admin_clave)
        headers = cabecera(token)

        base = {"email": f"dup_{p}@agas.test", "password": CLAVE}

        resp = client.post(_RUTA, headers=headers, json={**base, "username": existente.username})
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        resp = client.post(
            _RUTA, headers=headers, json={**base, "username": f"dup_{p}", "email": existente.email}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        resp = client.post(
            _RUTA,
            headers=headers,
            json={**base, "username": f"dup_{p}", "empleado_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        # empleado ya vinculado a otra cuenta → 409
        resp = client.post(
            _RUTA,
            headers=headers,
            json={**base, "username": f"dup_{p}", "empleado_id": str(existente.empleado_id)},
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # validaciones de formato → 422 con el manejador del proyecto
        resp = client.post(
            _RUTA, headers=headers, json={"username": "ab", "email": f"c_{p}@agas.test", "password": CLAVE}
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.post(
            _RUTA, headers=headers, json={"username": f"ok_{p}", "email": "sin-arroba", "password": CLAVE}
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


# ============================================================
# ACTUALIZACIÓN
# ============================================================


async def test_actualizar_usuario(session_factory) -> None:
    objetivo, _ = await crear_cadena_rbac(session_factory)
    otro, _ = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        token = token_de(client, admin, admin_clave)
        headers = cabecera(token)

        resp = client.patch(
            f"{_RUTA}/{objetivo.id}",
            headers=headers,
            json={"email": f"renombrado_{uuid.uuid4().hex[:8]}@agas.test"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"].startswith("renombrado_")

        # sin campos → 400 (no-op no permitido)
        resp = client.patch(f"{_RUTA}/{objetivo.id}", headers=headers, json={})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # username de otro usuario → 409
        resp = client.patch(f"{_RUTA}/{objetivo.id}", headers=headers, json={"username": otro.username})
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # conservar el propio username → 200 (excluye el propio registro)
        resp = client.patch(f"{_RUTA}/{objetivo.id}", headers=headers, json={"username": objetivo.username})
        assert resp.status_code == 200

        resp = client.patch(f"{_RUTA}/{uuid.uuid4()}", headers=headers, json={"email": "a@b.cl"})
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


# ============================================================
# TRANSICIONES DE ESTADO
# ============================================================


async def test_transicion_estado_bloquea_y_reactiva(session_factory) -> None:
    objetivo, clave = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        token_objetivo = token_de(client, objetivo, clave)
        token_admin = token_de(client, admin, admin_clave)
        headers = cabecera(token_admin)

        # el usuario está activo: /me funciona
        resp = client.get("/api/v1/auth/me", headers=cabecera(token_objetivo))
        assert resp.status_code == 200

        # ACTIVO → BLOQUEADO
        resp = client.patch(
            f"{_RUTA}/{objetivo.id}/estado", headers=headers, json={"estado": "BLOQUEADO"}
        )
        assert resp.status_code == 200
        assert resp.json()["estado"] == "BLOQUEADO"

        # con el mismo access token → 401 (la cuenta está bloqueada)
        resp = client.get("/api/v1/auth/me", headers=cabecera(token_objetivo))
        assert resp.status_code == 401
        assert codigo_error(resp) == "ACCOUNT_BLOCKED"

        # misma transición dos veces → 409 con los destinos posibles
        resp = client.patch(
            f"{_RUTA}/{objetivo.id}/estado", headers=headers, json={"estado": "BLOQUEADO"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert "ACTIVO" in resp.json()["detail"]["extra"]["allowed_states"]

        # estado fuera del ciclo → 422
        resp = client.patch(
            f"{_RUTA}/{objetivo.id}/estado", headers=headers, json={"estado": "ELIMINADO"}
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # BLOQUEADO → ACTIVO reactiva el acceso
        resp = client.patch(
            f"{_RUTA}/{objetivo.id}/estado", headers=headers, json={"estado": "ACTIVO"}
        )
        assert resp.status_code == 200
        resp = client.get("/api/v1/auth/me", headers=cabecera(token_objetivo))
        assert resp.status_code == 200


async def test_transicion_estado_revoca_sesiones_vivas(session_factory) -> None:
    objetivo, clave = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        token_de(client, objetivo, clave)  # crea una sesión viva
        token_admin = token_de(client, admin, admin_clave)

        resp = client.patch(
            f"{_RUTA}/{objetivo.id}/estado",
            headers=cabecera(token_admin),
            json={"estado": "EXPIRADO"},
        )
        assert resp.status_code == 200

    async with session_factory() as session:
        sesiones = (
            await session.execute(select(Sesion).where(Sesion.usuario_id == objetivo.id))
        ).scalars().all()
    assert sesiones, "el login debió registrar sesión"
    assert all(s.revocada for s in sesiones)


# ============================================================
# RESETEO DE CONTRASEÑA
# ============================================================


async def test_resetear_password_revoca_sesiones_y_cambia_acceso(session_factory) -> None:
    objetivo, clave_vieja = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    clave_nueva = "NuevaClave2026!"
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, admin_clave))
        refresh_viejo = login(client, objetivo.username, clave_vieja).json()["refresh_token"]

        # contraseña que viola la política → 400
        resp = client.put(
            f"{_RUTA}/{objetivo.id}/password", headers=headers, json={"password": "12345678"}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "PASSWORD_POLICY_ERROR"

        resp = client.put(
            f"{_RUTA}/{objetivo.id}/password", headers=headers, json={"password": clave_nueva}
        )
        assert resp.status_code == 200
        assert resp.json()["requiere_cambio_password"] is True

        # la clave vieja ya no sirve
        assert login(client, objetivo.username, clave_vieja).status_code == 401
        # la nueva sí
        assert login(client, objetivo.username, clave_nueva).status_code == 200
        # y la sesión anterior quedó revocada → refresh con el token viejo falla
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_viejo})
        assert resp.status_code == 401


# ============================================================
# ANULACIÓN LÓGICA
# ============================================================


async def test_anular_usuario_es_bloqueo_con_sesiones_revocadas(session_factory) -> None:
    objetivo, clave = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, admin_clave))
        token_objetivo = token_de(client, objetivo, clave)

        resp = client.delete(f"{_RUTA}/{objetivo.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["estado"] == "BLOQUEADO"

        # el token previo queda inútil
        resp = client.get("/api/v1/auth/me", headers=cabecera(token_objetivo))
        assert resp.status_code == 401
        assert codigo_error(resp) == "ACCOUNT_BLOCKED"

        # idempotente: anular dos veces devuelve 200 otra vez
        resp = client.delete(f"{_RUTA}/{objetivo.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["estado"] == "BLOQUEADO"

        resp = client.delete(f"{_RUTA}/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

    async with session_factory() as session:
        sesiones = (
            await session.execute(select(Sesion).where(Sesion.usuario_id == objetivo.id))
        ).scalars().all()
    assert sesiones
    assert all(s.revocada for s in sesiones)


# ============================================================
# SEMÁNTICA DE `null` Y VINCULACIÓN DE EMPLEADO
# ============================================================


async def test_parchear_con_null_no_modifica(session_factory) -> None:
    """`null` = sin cambio: solo nulls → 400; null junto a un valor lo ignora."""
    objetivo, _ = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, admin_clave))

        resp = client.patch(f"{_RUTA}/{objetivo.id}", headers=headers, json={"email": None})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        nuevo_email = f"null_{uuid.uuid4().hex[:8]}@agas.test"
        resp = client.patch(
            f"{_RUTA}/{objetivo.id}",
            headers=headers,
            json={"username": None, "email": nuevo_email},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == objetivo.username
        assert resp.json()["email"] == nuevo_email


async def test_vincular_empleado_por_parche(session_factory) -> None:
    usuario, _ = await crear_usuario(session_factory)
    empleado_libre, _ = await crear_empleado(session_factory)
    vinculado, _ = await crear_cadena_rbac(session_factory)
    admin, admin_clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS_USUARIOS
    )
    with TestClient(app) as client:
        headers = cabecera(token_de(client, admin, admin_clave))

        resp = client.patch(
            f"{_RUTA}/{usuario.id}", headers=headers, json={"empleado_id": str(uuid.uuid4())}
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"

        resp = client.patch(
            f"{_RUTA}/{usuario.id}",
            headers=headers,
            json={"empleado_id": str(vinculado.empleado_id)},
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        resp = client.patch(
            f"{_RUTA}/{usuario.id}", headers=headers, json={"empleado_id": str(empleado_libre.id)}
        )
        assert resp.status_code == 200
        assert resp.json()["empleado_id"] == str(empleado_libre.id)


async def test_verificar_unico_acepta_valor_nulo(session_factory) -> None:
    """Un valor nulo nunca choca: la unicidad solo aplica a valores reales."""
    async with session_factory() as session:
        assert await verificar_unico(session, Usuario, "username", None) is None
