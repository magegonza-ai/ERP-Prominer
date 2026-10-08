"""
Tests de la subetapa 3.2: parámetros del sistema y tasas de impuesto.

Parámetros: PK natural `clave`, coacción de `valor` al `tipo` declarado
(400 si no corresponde), `clave`/`tipo` inmutables, `editable=false` →
409 READONLY en PATCH y DELETE, guards TAREA_29.
Tasas de impuesto: CRUD con vigencias, `valor` acotado [0, 100] (422),
`vigencia_desde <= vigencia_hasta` (400), un solo `es_default` global
(auto-revocación), `cerrar_vigencia` y DELETE condicionado a referencias
(409 HAS_HISTORY).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from factories import (
    TAREA_CATALOGOS,
    TAREA_USUARIOS,
    cabecera,
    codigo_error,
    crear_cadena_rbac,
    prefijo,
    token_de,
)
from fastapi.testclient import TestClient

from app.main import app
from app.models import Categoria, Producto

_RUTA_PARAMETROS = "/api/v1/parametros"
_RUTA_TASAS = "/api/v1/tasas-impuesto"
_PERMISOS = ["PERM_01", "PERM_02", "PERM_03", "PERM_07"]

HOY = date.today()


def _admin(client: TestClient, user, clave: str) -> dict:
    return cabecera(token_de(client, user, clave))


async def _admin_catalogos(session_factory):
    return await crear_cadena_rbac(
        session_factory, tareas=[TAREA_CATALOGOS], permisos=_PERMISOS
    )


async def _admin_solo_usuarios(session_factory):
    return await crear_cadena_rbac(
        session_factory, tareas=[TAREA_USUARIOS], permisos=_PERMISOS
    )


# ============================================================
# GUARDS RBAC
# ============================================================


@pytest.mark.parametrize("ruta", [_RUTA_PARAMETROS, _RUTA_TASAS])
def test_3_2_sin_token_401(ruta: str) -> None:
    with TestClient(app) as client:
        resp = client.get(ruta)
        assert resp.status_code == 401
        assert codigo_error(resp) == "UNAUTHORIZED"


@pytest.mark.parametrize("ruta", [_RUTA_PARAMETROS, _RUTA_TASAS])
async def test_3_2_dominio_equivocado_403(session_factory, ruta: str) -> None:
    """TAREA_28 (usuarios) no da acceso al dominio TAREA_29 (catálogos)."""
    user, clave = await _admin_solo_usuarios(session_factory)
    with TestClient(app) as client:
        resp = client.get(ruta, headers=_admin(client, user, clave))
        assert resp.status_code == 403
        assert codigo_error(resp) == "PERMISSION_DENIED"


# ============================================================
# PARÁMETROS
# ============================================================


async def test_parametro_crud_completo(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        clave_param = f"test.{prefijo()[:10]}"

        # Alta con defaults (editable=true, sin actualización previa)
        resp = client.post(
            _RUTA_PARAMETROS,
            headers=headers,
            json={"clave": clave_param, "valor": "hola", "tipo": "STRING", "descripcion": "prueba"},
        )
        assert resp.status_code == 201, resp.text
        creado = resp.json()
        assert creado["clave"] == clave_param
        assert creado["editable"] is True
        assert creado["actualizada_por"] is None
        assert creado["fecha_actualizacion"]

        # Detalle por clave natural + listado con `q` y `tipo`
        resp = client.get(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["valor"] == "hola"
        resp = client.get(_RUTA_PARAMETROS, headers=headers, params={"q": clave_param})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["clave"] == clave_param
        resp = client.get(
            _RUTA_PARAMETROS, headers=headers, params={"q": clave_param, "tipo": "STRING"}
        )
        assert resp.json()["total"] == 1
        resp = client.get(
            _RUTA_PARAMETROS, headers=headers, params={"q": clave_param, "tipo": "INTEGER"}
        )
        assert resp.json()["total"] == 0

        # Actualización: registra al usuario autenticado
        resp = client.patch(
            f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers, json={"valor": "adios"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["valor"] == "adios"
        assert resp.json()["actualizada_por"] == str(user.id)

        resp = client.patch(
            f"{_RUTA_PARAMETROS}/{clave_param}",
            headers=headers,
            json={"descripcion": "actualizada"},
        )
        assert resp.status_code == 200
        assert resp.json()["descripcion"] == "actualizada"
        assert resp.json()["valor"] == "adios"  # sin cambio

        # Borrado físico y detalle posterior → 404
        assert client.delete(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers).status_code == 204
        resp = client.get(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"


async def test_parametro_clave_duplicada_409(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        clave_param = f"test.{prefijo()[:10]}"
        body = {"clave": clave_param, "valor": "1", "tipo": "INTEGER"}
        assert client.post(_RUTA_PARAMETROS, headers=headers, json=body).status_code == 201
        resp = client.post(_RUTA_PARAMETROS, headers=headers, json=body)
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"
        client.delete(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers)


async def test_parametro_tipo_invalido_422(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.post(
            _RUTA_PARAMETROS,
            headers=headers,
            json={"clave": f"test.{prefijo()[:10]}", "valor": "x", "tipo": "ENTERO"},
        )
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("tipo", "valor_ok", "valor_malo"),
    [
        ("INTEGER", "42", "abc"),
        ("DECIMAL", "19.50", "carne"),
        ("DECIMAL", "2", "Infinity"),  # parsea pero no es finito -> invalido
        ("BOOLEAN", "TRUE", "si"),
        ("BOOLEAN", "1", None),
        ("JSON", '{"iva": 19}', "{iva:19"),
        ("DATE", "2026-12-31", "31/12/2026"),
        ("STRING", "cualquier cosa; 123", None),
    ],
)
async def test_parametro_coaccion_valor(
    session_factory, tipo: str, valor_ok: str, valor_malo: str | None
) -> None:
    """El `valor` debe coaccionar al `tipo` declarado del parámetro."""
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        base = {"clave": f"test.{prefijo()[:10]}", "tipo": tipo}

        resp = client.post(_RUTA_PARAMETROS, headers=headers, json={**base, "valor": valor_ok})
        assert resp.status_code == 201, f"{tipo}/{valor_ok} debió ser válido: {resp.text}"
        assert resp.json()["tipo"] == tipo
        client.delete(f"{_RUTA_PARAMETROS}/{base['clave']}", headers=headers)

        if valor_malo is not None:
            resp = client.post(
                _RUTA_PARAMETROS, headers=headers, json={**base, "valor": valor_malo}
            )
            assert resp.status_code == 400, f"{tipo}/{valor_malo} debió ser inválido"
            assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_parametro_no_editable_readonly(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        clave_param = f"test.{prefijo()[:10]}"
        resp = client.post(
            _RUTA_PARAMETROS,
            headers=headers,
            json={"clave": clave_param, "valor": "fijo", "tipo": "STRING", "editable": False},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["editable"] is False

        # PATCH y DELETE rechazados → 409 READONLY (solo seed/migración)
        resp = client.patch(
            f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers, json={"valor": "nuevo"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "READONLY"
        resp = client.patch(
            f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers, json={"descripcion": "x"}
        )
        assert resp.status_code == 409
        assert codigo_error(resp) == "READONLY"
        resp = client.delete(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "READONLY"

        # Sigue consultable
        assert client.get(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers).status_code == 200


async def test_parametro_clave_y_tipo_inmutables(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        clave_param = f"test.{prefijo()[:10]}"
        client.post(
            _RUTA_PARAMETROS,
            headers=headers,
            json={"clave": clave_param, "valor": "x", "tipo": "STRING"},
        )

        # Ni `clave` (PK) ni `tipo` están en el esquema Update → nada que actualizar
        resp = client.patch(
            f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers, json={"clave": "otra.clave"}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        resp = client.patch(
            f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers, json={"tipo": "INTEGER"}
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers)


async def test_parametro_null_significa_sin_cambio(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        clave_param = f"test.{prefijo()[:10]}"
        resp = client.post(
            _RUTA_PARAMETROS,
            headers=headers,
            json={"clave": clave_param, "valor": "original", "tipo": "STRING"},
        )
        assert resp.status_code == 201

        # Solo nulls → 400; null + valor real → se aplica solo el valor
        resp = client.patch(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers, json={"valor": None})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        resp = client.patch(
            f"{_RUTA_PARAMETROS}/{clave_param}",
            headers=headers,
            json={"valor": None, "descripcion": "obs"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["valor"] == "original"
        assert resp.json()["descripcion"] == "obs"

        client.delete(f"{_RUTA_PARAMETROS}/{clave_param}", headers=headers)


async def test_parametro_desconocido_404(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        inexistente = f"no.existe.{prefijo()[:8]}"
        resp = client.get(f"{_RUTA_PARAMETROS}/{inexistente}", headers=headers)
        assert resp.status_code == 404
        assert codigo_error(resp) == "NOT_FOUND"
        assert client.patch(
            f"{_RUTA_PARAMETROS}/{inexistente}", headers=headers, json={"valor": "x"}
        ).status_code == 404
        assert client.delete(f"{_RUTA_PARAMETROS}/{inexistente}", headers=headers).status_code == 404


# ============================================================
# TASAS DE IMPUESTO
# ============================================================


async def test_tasa_crud_completo(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = f"T{prefijo()[:9]}"

        # Alta con defaults del modelo
        resp = client.post(
            _RUTA_TASAS,
            headers=headers,
            json={"codigo": codigo, "nombre": "IVA Prueba", "valor": 16.5},
        )
        assert resp.status_code == 201, resp.text
        creado = resp.json()
        rid = creado["id"]
        assert creado["estado"] == "ACTIVA"
        assert creado["es_default"] is False
        assert creado["vigencia_desde"] == HOY.isoformat()
        assert creado["vigencia_hasta"] is None

        # Detalle + listado por `q` (único por el código)
        assert client.get(f"{_RUTA_TASAS}/{rid}", headers=headers).json()["id"] == rid
        resp = client.get(_RUTA_TASAS, headers=headers, params={"q": codigo})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == rid

        # Actualización parcial (nombre y valor decimal exacto)
        resp = client.patch(
            f"{_RUTA_TASAS}/{rid}", headers=headers, json={"nombre": "IVA 19", "valor": 19.5}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["nombre"] == "IVA 19"
        assert Decimal(str(resp.json()["valor"])) == Decimal("19.5")

        # Transición de estado + filtro por estado
        resp = client.patch(f"{_RUTA_TASAS}/{rid}/estado", headers=headers, json={"estado": "INACTIVA"})
        assert resp.status_code == 200
        resp = client.get(_RUTA_TASAS, headers=headers, params={"q": codigo, "estado": "INACTIVA"})
        assert resp.json()["total"] == 1
        resp = client.get(_RUTA_TASAS, headers=headers, params={"q": codigo, "estado": "ACTIVA"})
        assert resp.json()["total"] == 0

        # Borrado físico (cero referencias) y detalle posterior → 404
        assert client.delete(f"{_RUTA_TASAS}/{rid}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA_TASAS}/{rid}", headers=headers).status_code == 404


async def test_tasa_codigo_duplicado_e_inmutable(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = f"T{prefijo()[:9]}"
        body = {"codigo": codigo, "nombre": "IVA", "valor": 19}
        assert client.post(_RUTA_TASAS, headers=headers, json=body).status_code == 201

        resp = client.post(_RUTA_TASAS, headers=headers, json=body)
        assert resp.status_code == 409
        assert codigo_error(resp) == "DUPLICATE_VALUE"

        # `codigo` no está en el esquema Update → nada que actualizar
        rid = client.get(_RUTA_TASAS, headers=headers, params={"q": codigo}).json()["items"][0]["id"]
        resp = client.patch(f"{_RUTA_TASAS}/{rid}", headers=headers, json={"codigo": "OTRO"})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_TASAS}/{rid}", headers=headers)


async def test_tasa_valor_fuera_de_rango_422(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        for valor in (-0.01, 100.01, 250):
            resp = client.post(
                _RUTA_TASAS,
                headers=headers,
                json={"codigo": f"T{prefijo()[:9]}", "nombre": "IVA", "valor": valor},
            )
            assert resp.status_code == 422, f"valor {valor} debió ser inválido"
            assert codigo_error(resp) == "VALIDATION_ERROR"


async def test_tasa_vigencia_invertida_400(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        # En el alta
        resp = client.post(
            _RUTA_TASAS,
            headers=headers,
            json={
                "codigo": f"T{prefijo()[:9]}",
                "nombre": "IVA",
                "valor": 19,
                "vigencia_desde": (HOY + timedelta(days=10)).isoformat(),
                "vigencia_hasta": (HOY + timedelta(days=5)).isoformat(),
            },
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        # En la actualización (la coherencia se re-valida con los valores efectivos)
        rid = client.post(
            _RUTA_TASAS, headers=headers, json={"codigo": f"T{prefijo()[:9]}", "nombre": "IVA", "valor": 19}
        ).json()["id"]
        resp = client.patch(
            f"{_RUTA_TASAS}/{rid}",
            headers=headers,
            json={
                "vigencia_desde": (HOY + timedelta(days=10)).isoformat(),
                "vigencia_hasta": (HOY + timedelta(days=5)).isoformat(),
            },
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        client.delete(f"{_RUTA_TASAS}/{rid}", headers=headers)


async def test_tasa_cerrar_vigencia(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rid = client.post(
            _RUTA_TASAS, headers=headers, json={"codigo": f"T{prefijo()[:9]}", "nombre": "IVA", "valor": 19}
        ).json()["id"]

        # Cerrar hoy / abrir sin cierre (el interruptor `cerrar_vigencia`)
        resp = client.patch(f"{_RUTA_TASAS}/{rid}", headers=headers, json={"cerrar_vigencia": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["vigencia_hasta"] == HOY.isoformat()
        resp = client.patch(f"{_RUTA_TASAS}/{rid}", headers=headers, json={"cerrar_vigencia": False})
        assert resp.status_code == 200
        assert resp.json()["vigencia_hasta"] is None

        # Fecha explícita también cierra
        resp = client.patch(
            f"{_RUTA_TASAS}/{rid}",
            headers=headers,
            json={"vigencia_hasta": (HOY + timedelta(days=30)).isoformat()},
        )
        assert resp.status_code == 200
        assert resp.json()["vigencia_hasta"] == (HOY + timedelta(days=30)).isoformat()

        # Combinar `cerrar_vigencia` con `vigencia_hasta` explícito → 400
        resp = client.patch(
            f"{_RUTA_TASAS}/{rid}",
            headers=headers,
            json={"cerrar_vigencia": True, "vigencia_hasta": HOY.isoformat()},
        )
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_TASAS}/{rid}", headers=headers)


async def test_tasa_unico_es_default(session_factory) -> None:
    """Máximo una tasa `es_default` global: marcarla revoca la de las demás."""
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)

        def crear(codigo: str) -> str:
            resp = client.post(
                _RUTA_TASAS,
                headers=headers,
                json={"codigo": codigo, "nombre": "IVA", "valor": 19, "es_default": True},
            )
            assert resp.status_code == 201, resp.text
            return resp.json()["id"]

        def es_default(rid: str) -> bool:
            return client.get(f"{_RUTA_TASAS}/{rid}", headers=headers).json()["es_default"]

        codigo_a = f"A{prefijo()[:9]}"
        codigo_b = f"B{prefijo()[:9]}"
        tasa_a = crear(codigo_a)
        assert es_default(tasa_a) is True

        tasa_b = crear(codigo_b)  # al crear otra default, la anterior se revoca
        assert es_default(tasa_b) is True
        assert es_default(tasa_a) is False

        resp = client.patch(f"{_RUTA_TASAS}/{tasa_a}", headers=headers, json={"es_default": True})
        assert resp.status_code == 200, resp.text
        assert es_default(tasa_a) is True
        assert es_default(tasa_b) is False

        assert client.delete(f"{_RUTA_TASAS}/{tasa_a}", headers=headers).status_code == 204
        assert client.delete(f"{_RUTA_TASAS}/{tasa_b}", headers=headers).status_code == 204


async def test_tasa_transiciones_de_estado(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rid = client.post(
            _RUTA_TASAS, headers=headers, json={"codigo": f"T{prefijo()[:9]}", "nombre": "IVA", "valor": 19}
        ).json()["id"]

        assert client.patch(
            f"{_RUTA_TASAS}/{rid}/estado", headers=headers, json={"estado": "INACTIVA"}
        ).status_code == 200
        resp = client.patch(f"{_RUTA_TASAS}/{rid}/estado", headers=headers, json={"estado": "INACTIVA"})
        assert resp.status_code == 409
        assert codigo_error(resp) == "INVALID_STATE_TRANSITION"
        assert resp.json()["detail"]["extra"]["allowed_states"] == ["ACTIVA"]

        resp = client.patch(f"{_RUTA_TASAS}/{rid}/estado", headers=headers, json={"estado": "OTRO"})
        assert resp.status_code == 422
        assert codigo_error(resp) == "VALIDATION_ERROR"

        client.delete(f"{_RUTA_TASAS}/{rid}", headers=headers)


async def test_tasa_null_significa_sin_cambio(session_factory) -> None:
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        rid = client.post(
            _RUTA_TASAS, headers=headers, json={"codigo": f"T{prefijo()[:9]}", "nombre": "IVA", "valor": 19}
        ).json()["id"]

        resp = client.patch(f"{_RUTA_TASAS}/{rid}", headers=headers, json={"nombre": None})
        assert resp.status_code == 400
        assert codigo_error(resp) == "VALIDATION_ERROR"
        resp = client.patch(
            f"{_RUTA_TASAS}/{rid}", headers=headers, json={"nombre": None, "valor": 16}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["nombre"] == "IVA"
        assert Decimal(str(resp.json()["valor"])) == Decimal("16")

        client.delete(f"{_RUTA_TASAS}/{rid}", headers=headers)


async def test_tasa_delete_con_referencias_409(session_factory) -> None:
    """Con productos que la referencian → 409; sin ellas → 204."""
    user, clave = await _admin_catalogos(session_factory)
    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        codigo = f"T{prefijo()[:9]}"
        tasa = client.post(
            _RUTA_TASAS, headers=headers, json={"codigo": codigo, "nombre": "IVA", "valor": 19}
        )
        assert tasa.status_code == 201, tasa.text
        tasa_id = tasa.json()["id"]

    async with session_factory() as session:
        categoria = Categoria(tipo="PRODUCTO", codigo=f"CAT{prefijo()[:8]}", nombre="Ref tasa")
        session.add(categoria)
        await session.flush()
        producto = Producto(
            codigo=f"PRD{prefijo()[:8]}",
            nombre="Producto que referencia la tasa",
            categoria_id=categoria.id,
            unidad_medida="UN",
            tasa_impuesto_id=uuid.UUID(tasa_id),
        )
        session.add(producto)
        await session.commit()
        producto_id = producto.id
        categoria_id = categoria.id

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        resp = client.delete(f"{_RUTA_TASAS}/{tasa_id}", headers=headers)
        assert resp.status_code == 409
        assert codigo_error(resp) == "HAS_HISTORY"

    # Sin la referencia, el borrado físico procede
    async with session_factory() as session:
        producto = await session.get(Producto, producto_id)
        assert producto is not None
        await session.delete(producto)
        categoria = await session.get(Categoria, categoria_id)
        assert categoria is not None
        await session.delete(categoria)
        await session.commit()

    with TestClient(app) as client:
        headers = _admin(client, user, clave)
        assert client.delete(f"{_RUTA_TASAS}/{tasa_id}", headers=headers).status_code == 204
        assert client.get(f"{_RUTA_TASAS}/{tasa_id}", headers=headers).status_code == 404
