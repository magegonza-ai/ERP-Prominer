"""
Tests de los catálogos simples (subetapa 3.1): áreas, categorías
(jerárquicas), tipos de gas, formas de pago y tipos de documento.

Cubren: guards RBAC (TAREA_29 + acciones, 401 y 403 cross-dominio), CRUD
uniforme parametrizado, unicidad e inmutabilidad de `codigo`, transiciones
de estado, semántica `null` de PATCH, paginación, borrado condicionado a
referencias (409 HAS_HISTORY) y la jerarquía de categorías (padre
inexistente, auto-padre, ciclos).
"""

from __future__ import annotations

import uuid

import pytest
from factories import (
    TAREA_CATALOGOS,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    obtener_o_crear_area,
    prefijo,
    token_de,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Area

_RUTA_CATALOGOS = "/api/v1/areas"  # ruta base usada por los guards 401/403
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]

# (ruta, create_extra, patch_extra_sin_nombre, (estado_inicial, estado_nuevo))
CASOS = [
    pytest.param(
        "/api/v1/areas",
        {"nombre": "Área X", "orden_visual": 0},
        {"orden_visual": 5},
        ("ACTIVA", "INACTIVA"),
        id="areas",
    ),
    pytest.param(
        "/api/v1/categorias",
        {"tipo": "PRODUCTO", "nombre": "Categoría X"},
        {"descripcion": "obs"},
        ("ACTIVA", "INACTIVA"),
        id="categorias",
    ),
    pytest.param(
        "/api/v1/tipos-gas",
        {"nombre": "Gas X"},
        {"requiere_prueba_hidraulica": False},
        ("ACTIVO", "INACTIVO"),
        id="tipos-gas",
    ),
    pytest.param(
        "/api/v1/formas-pago",
        {"nombre": "Forma X"},
        {"es_tributario": True},
        ("ACTIVA", "INACTIVA"),
        id="formas-pago",
    ),
    pytest.param(
        "/api/v1/tipos-documento",
        {"nombre": "Tipo X"},
        {"requiere_receptor": False},
        ("ACTIVO", "INACTIVO"),
        id="tipos-documento",
    ),
]


def _codigo() -> str:
    return f"C{prefijo()[:10]}"


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _admin_catalogos(session_factory):
    return await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS
    )


# ============================================================
# GUARDS RBAC
# ============================================================


@pytest.mark.parametrize("ruta", [c.values[0] for c in CASOS])
def test_catalogos_sin_token_401(ruta: str) -> None:
    with TestClient(app) as client:
        resp = client.get(ruta)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


@pytest.mark.parametrize("ruta", [c.values[0] for c in CASOS])
async def test_catalogos_dominio_equivocado_403(session_factory, ruta: str) -> None:
    """TAREA_28 (usuarios) no da acceso al dominio TAREA_29 (catálogos)."""
    user, clave = await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS
    )
    with TestClient(app) as client:
        resp = client.get(ruta, headers=_admin(client, user, clave))
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


# ============================================================
# CRUD UNIFORME (parametrizado por módulo)
# ============================================================


@pytest.mark.parametrize(
    ("ruta", "extra", "patch_extra", "_estados"),
    CASOS,
)
async def test_crud_completo(
    session_factory, ruta: str, extra: dict, patch_extra: dict, _estados
) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = _codigo()

        # Alta con defaults del modelo
        resp = client.post(
            ruta, headers=headers, json={"codigo": codigo, **extra}
        )
        assert resp.status_code == 201, resp.text
        creado = resp.json()
        assert creado["codigo"] == codigo
        assert creado["fecha_creacion"]

        # Detalle + listado por `q` (único por el código)
        rid = creado["id"]
        assert client.get(f"{ruta}/{rid}", headers=headers).json()["id"] == rid
        resp = client.get(ruta, headers=headers, params={"q": codigo})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == rid

        # Actualización parcial
        cambios = {"nombre": f"{extra['nombre']} (editada)", **patch_extra}
        resp = client.patch(f"{ruta}/{rid}", headers=headers, json=cambios)
        assert resp.status_code == 200, resp.text
        for campo, valor in cambios.items():
            assert resp.json()[campo] == valor

        # Transición de estado y filtro por estado
        estado_inicial, estado_nuevo = _estados
        resp = client.patch(f"{ruta}/{rid}/estado", headers=headers, json={"estado": estado_nuevo})
        assert resp.status_code == 200
        assert resp.json()["estado"] == estado_nuevo
        resp = client.get(ruta, headers=headers, params={"q": codigo, "estado": estado_nuevo})
        assert resp.json()["total"] == 1
        resp = client.get(ruta, headers=headers, params={"q": codigo, "estado": estado_inicial})
        assert resp.json()["total"] == 0

        # Borrado físico (cero referencias) y detalle posterior → 404
        assert client.delete(f"{ruta}/{rid}", headers=headers).status_code == 204
        assert client.get(f"{ruta}/{rid}", headers=headers).status_code == 404


@pytest.mark.parametrize(
    ("ruta", "extra", "_patch_extra", "_estados"),
    CASOS,
)
async def test_codigo_duplicado_409(
    session_factory, ruta: str, extra: dict, _patch_extra, _estados
) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = _codigo()

        assert client.post(ruta, headers=headers, json={"codigo": codigo, **extra}).status_code == 201
        resp = client.post(ruta, headers=headers, json={"codigo": codigo, **extra})
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"


@pytest.mark.parametrize(
    ("ruta", "extra", "_patch_extra", "_estados"),
    CASOS,
)
async def test_codigo_inmutable_en_parche(
    session_factory, ruta: str, extra: dict, _patch_extra, _estados
) -> None:
    """PATCH solo con `codigo` → 400: el campo no está en el esquema Update."""
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = _codigo()
        rid = client.post(ruta, headers=headers, json={"codigo": codigo, **extra}).json()["id"]

        resp = client.patch(f"{ruta}/{rid}", headers=headers, json={"codigo": _codigo()})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{ruta}/{rid}", headers=headers)


@pytest.mark.parametrize(
    ("ruta", "extra", "_patch_extra", "estados"),
    CASOS,
)
async def test_transiciones_de_estado(
    session_factory, ruta: str, extra: dict, _patch_extra, estados
) -> None:
    estado_inicial, estado_nuevo = estados
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = _codigo()
        resp = client.post(ruta, headers=headers, json={"codigo": codigo, **extra})
        rid = resp.json()["id"]
        assert resp.json()["estado"] == estado_inicial

        # Misma transición dos veces → 409 con allowed_states
        assert client.patch(f"{ruta}/{rid}/estado", headers=headers, json={"estado": estado_nuevo}).status_code == 200
        resp = client.patch(f"{ruta}/{rid}/estado", headers=headers, json={"estado": estado_nuevo})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == [estado_inicial]

        # Estado fuera del Literal → 422
        resp = client.patch(f"{ruta}/{rid}/estado", headers=headers, json={"estado": "OTRO"})
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{ruta}/{rid}", headers=headers)


@pytest.mark.parametrize(
    ("ruta", "extra", "patch_extra_sin_nombre", "_estados"),
    CASOS,
)
async def test_parchear_con_null_no_modifica(
    session_factory, ruta: str, extra: dict, patch_extra_sin_nombre: dict, _estados
) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = _codigo()
        resp = client.post(ruta, headers=headers, json={"codigo": codigo, **extra})
        rid = resp.json()["id"]
        nombre_original = resp.json()["nombre"]

        # Solo nulls → 400 (nada que actualizar)
        resp = client.patch(f"{ruta}/{rid}", headers=headers, json={"nombre": None})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # null junto a un valor real → se aplica solo el valor
        resp = client.patch(
            f"{ruta}/{rid}",
            headers=headers,
            json={"nombre": None, **patch_extra_sin_nombre},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["nombre"] == nombre_original
        for campo, valor in patch_extra_sin_nombre.items():
            assert resp.json()[campo] == valor

        client.delete(f"{ruta}/{rid}", headers=headers)


@pytest.mark.parametrize("ruta", [c.values[0] for c in CASOS])
async def test_detalle_desconocido_404(session_factory, ruta: str) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        desconocido = str(uuid.uuid4())
        resp = client.get(f"{ruta}/{desconocido}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"
        assert client.patch(
            f"{ruta}/{desconocido}", headers=headers, json={"nombre": "x"}
        ).status_code == 404
        assert client.delete(f"{ruta}/{desconocido}", headers=headers).status_code == 404
        resp = client.get(f"{ruta}/no-es-uuid", headers=headers)
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


# ============================================================
# MÓDULO ESPECÍFICO: ÁREAS
# ============================================================


async def test_area_con_empleados_no_se_puede_eliminar(session_factory) -> None:
    """El área TESTAGAS tiene empleados (fixtures) → 409 HAS_HISTORY."""
    user, clave = await _admin_catalogos(session_factory)
    async with session_factory() as session:
        area = await obtener_o_crear_area(session)
        area_id = area.id
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.delete(f"/api/v1/areas/{area_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"


async def test_area_orden_visual_negativo_422(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            "/api/v1/areas",
            headers=headers,
            json={"codigo": _codigo(), "nombre": "Área", "orden_visual": -1},
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


# ============================================================
# MÓDULO ESPECÍFICO: CATEGORÍAS (jerarquía)
# ============================================================


async def test_categoria_jerarquia_completa(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo_raiz = _codigo()
        codigo_hija = _codigo()

        raiz = client.post(
            "/api/v1/categorias",
            headers=headers,
            json={"tipo": "AMBOS", "codigo": codigo_raiz, "nombre": "Raíz"},
        ).json()
        hija = client.post(
            "/api/v1/categorias",
            headers=headers,
            json={
                "tipo": "PRODUCTO",
                "codigo": codigo_hija,
                "nombre": "Hija",
                "padre_id": raiz["id"],
            },
        )
        assert hija.status_code == 201, hija.text
        assert hija.json()["padre_id"] == raiz["id"]

        hoja = client.post(
            "/api/v1/categorias",
            headers=headers,
            json={
                "tipo": "PRODUCTO",
                "codigo": _codigo(),
                "nombre": "Hoja",
                "padre_id": hija.json()["id"],
            },
        ).json()

        # Filtro por madre y por tipo
        resp = client.get(
            "/api/v1/categorias",
            headers=headers,
            params={"padre_id": raiz["id"], "q": codigo_hija},
        )
        assert resp.json()["total"] == 1
        resp = client.get(
            "/api/v1/categorias",
            headers=headers,
            params={"tipo": "PRODUCTO", "q": codigo_hija},
        )
        assert resp.json()["total"] == 1
        resp = client.get(
            "/api/v1/categorias",
            headers=headers,
            params={"tipo": "SERVICIO", "q": codigo_hija},
        )
        assert resp.json()["total"] == 0

        # Reasignar la raíz bajo su descendiente 2 niveles más abajo → ciclo
        resp = client.patch(
            f"/api/v1/categorias/{raiz['id']}",
            headers=headers,
            json={"padre_id": hoja["id"]},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # La hija no puede ser su propia madre
        resp = client.patch(
            f"/api/v1/categorias/{hija.json()['id']}",
            headers=headers,
            json={"padre_id": hija.json()["id"]},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # Borrar con descendientes → 409; de hoja a raíz → 204
        resp = client.delete(f"/api/v1/categorias/{raiz['id']}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"
        assert client.delete(f"/api/v1/categorias/{hoja['id']}", headers=headers).status_code == 204
        assert client.delete(f"/api/v1/categorias/{hija.json()['id']}", headers=headers).status_code == 204
        assert client.delete(f"/api/v1/categorias/{raiz['id']}", headers=headers).status_code == 204


async def test_categoria_padre_inexistente_404(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            "/api/v1/categorias",
            headers=headers,
            json={
                "tipo": "PRODUCTO",
                "codigo": _codigo(),
                "nombre": "Huérfana",
                "padre_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_categoria_tipo_invalido_422(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            "/api/v1/categorias",
            headers=headers,
            json={"tipo": "GAS", "codigo": _codigo(), "nombre": "X"},
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


# ============================================================
# MÓDULO ESPECÍFICO: TIPOS DE GAS
# ============================================================


async def test_tipo_gas_color_de_etiqueta(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        for color in ("rojo", "#FFF", "#GGGGGG"):
            resp = client.post(
                "/api/v1/tipos-gas",
                headers=headers,
                json={"codigo": _codigo(), "nombre": "Gas", "color_etiqueta": color},
            )
            assert resp.status_code == 422, f"color {color!r} debió ser inválido"
            assert codigo_error(resp) == "VALIDATION_ERROR"

        resp = client.post(
            "/api/v1/tipos-gas",
            headers=headers,
            json={"codigo": _codigo(), "nombre": "Gas", "color_etiqueta": "#1A2B3c"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["requiere_prueba_hidraulica"] is True  # default del modelo
        assert resp.json()["color_etiqueta"] == "#1A2B3c"
        client.delete(f"/api/v1/tipos-gas/{resp.json()['id']}", headers=headers)


# ============================================================
# MÓDULO ESPECÍFICO: FORMAS DE PAGO Y TIPOS DE DOCUMENTO (defaults)
# ============================================================


async def test_forma_pago_defaults(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            "/api/v1/formas-pago",
            headers=headers,
            json={"codigo": _codigo(), "nombre": "Transferencia"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["es_tributario"] is False
        assert resp.json()["requiere_nro_operacion"] is True
        client.delete(f"/api/v1/formas-pago/{resp.json()['id']}", headers=headers)


async def test_tipo_documento_defaults(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            "/api/v1/tipos-documento",
            headers=headers,
            json={"codigo": _codigo(), "nombre": "Boleta"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["requiere_folio_unico"] is True
        assert resp.json()["requiere_receptor"] is True
        assert resp.json()["plantilla_pdf"] is None
        client.delete(f"/api/v1/tipos-documento/{resp.json()['id']}", headers=headers)


# ============================================================
# PAGINACIÓN
# ============================================================


async def test_listado_paginado_determinista(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        pref = f"Z{prefijo()[:8]}"
        creados = [
            client.post(
                "/api/v1/formas-pago",
                headers=headers,
                json={"codigo": f"{pref}{i}", "nombre": f"Pago {pref} {i}"},
            ).json()["id"]
            for i in range(3)
        ]
        try:
            resp = client.get(
                "/api/v1/formas-pago",
                headers=headers,
                params={"q": pref, "pagina": 1, "por_pagina": 2},
            )
            assert resp.status_code == 200
            datos = resp.json()
            assert datos["total"] == 3
            assert datos["paginas"] == 2
            assert len(datos["items"]) == 2
            assert all(i["id"] in creados for i in datos["items"])

            resp = client.get(
                "/api/v1/formas-pago",
                headers=headers,
                params={"q": pref, "pagina": 2, "por_pagina": 2},
            )
            assert len(resp.json()["items"]) == 1
        finally:
            for rid in creados:
                client.delete(f"/api/v1/formas-pago/{rid}", headers=headers)


# ============================================================
# ÁREA TESTAGAS INTACTA (el 409 no la borró)
# ============================================================


async def test_area_testagas_sigue_activa(session_factory) -> None:
    async with session_factory() as session:
        area = (
            await session.execute(select(Area).where(Area.codigo == "TESTAGAS"))
        ).scalar_one()
        assert area.estado == "ACTIVA"
