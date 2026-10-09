"""
Fábricas y helpers compartidos de los tests de la ETAPA 2.1.

Patrón get-or-create: la BD de pruebas `agas_cilindros_test` persiste entre
corridas locales, así que los códigos fijos del RBAC (TAREA_01/02/03/15/16/
28/29/30 y PERM_01..PERM_10) se reutilizan y su matriz `tarea_permiso` solo
se completa si falta la fila (y se repara su estado). En CI la BD nace vacía y
las fábricas crean todo desde cero.

Todos los usuarios/empleados creados usan prefijos uuid → únicos por test
(sin colisiones entre tests ni entre corridas).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.models import (
    Area,
    Empleado,
    EmpleadoTarea,
    Permiso,
    Tarea,
    TareaPermiso,
    Usuario,
)

CLAVE = "Admin2026!"  # política: mayúscula, minúscula, dígito y especial

# Códigos fijos del RBAC (scripts/seed_data.py).
TAREA_CLIENTES = "TAREA_01"  # registrar clientes (y receptores autorizados)
TAREA_PROPIETARIOS = "TAREA_02"  # registrar propietarios de cilindros
TAREA_CILINDROS = "TAREA_03"  # registrar cilindros (inventario)
TAREA_RECEPCION = "TAREA_04"  # recibir cilindros (operativo)
TAREA_INSPECCION = "TAREA_05"  # inspeccionar cilindros (calidad)
TAREA_LLENADO_CREAR = "TAREA_07"  # crear órdenes de llenado (operativo)
TAREA_LLENADO_EJECUTAR = "TAREA_08"  # ejecutar llenado (operativo)
TAREA_LLENADO_CERRAR = "TAREA_09"  # cerrar órdenes de llenado (operativo)
TAREA_REPARACION_CREAR = "TAREA_10"  # crear órdenes de reparación (operativo)
TAREA_DIAGNOSTICO = "TAREA_11"  # diagnosticar fallas (operativo)
TAREA_REPARACION_EJECUTAR = "TAREA_12"  # ejecutar reparaciones (operativo)
TAREA_REPARACION_CERRAR = "TAREA_13"  # cerrar órdenes de reparación (operativo)
TAREA_CONTROL_CALIDAD = "TAREA_14"  # realizar control de calidad (operativo)
TAREA_PREPARAR_ENTREGAS = "TAREA_17"  # preparar despachos y entregas (operativo)
TAREA_ENTREGAR = "TAREA_18"  # entregar cilindros en terreno (operativo)
TAREA_REGISTRAR_DEVOLUCIONES = "TAREA_19"  # registrar devoluciones de cilindros (operativo)
TAREA_CAMBIO_UBICACION = "TAREA_15"  # cambiar ubicación (operativo)
TAREA_MOVIMIENTOS = "TAREA_16"  # registrar movimientos (operativo)
TAREA_USUARIOS = "TAREA_28"  # administrar usuarios, empleados y sesiones
TAREA_CATALOGOS = "TAREA_29"  # administrar catálogos (tareas y permisos)
TAREA_AUDITORIA = "TAREA_30"  # revisar la bitácora de auditoría
PERMISOS_TODOS = tuple(f"PERM_{n:02d}" for n in range(1, 11))


# ============================================================
# HELPERS SÍNCRONOS (respuestas HTTP)
# ============================================================


def prefijo() -> str:
    return uuid.uuid4().hex[:12]


def cabecera(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def codigo_error(resp) -> str:
    return resp.json()["detail"]["code"]


def login(client: TestClient, username: str, password: str, totp_code: str | None = None):
    payload = {"username": username, "password": password}
    if totp_code is not None:
        payload["totp_code"] = totp_code
    return client.post("/api/v1/auth/login", json=payload)


def token_de(client: TestClient, user: Usuario, clave: str = CLAVE) -> str:
    """Login y devuelve el access token (falla el test si el login no es 200)."""
    resp = login(client, user.username, clave)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ============================================================
# GET-OR-CREATE DEL CATÁLOGO FIJO
# ============================================================


async def _get_o_crear(session, model, defaults: dict, **filtros):
    stmt = select(model).where(*[getattr(model, k) == v for k, v in filtros.items()])
    fila = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if fila is None:
        fila = model(**filtros, **defaults)
        session.add(fila)
        await session.flush()
    return fila


async def obtener_o_crear_area(session) -> Area:
    return await _get_o_crear(
        session,
        Area,
        {"nombre": "Área de pruebas (fixture)"},
        codigo="TESTAGAS",
    )


async def obtener_o_crear_tarea(session, codigo: str) -> Tarea:
    tarea = await _get_o_crear(
        session,
        Tarea,
        {"nombre": f"Tarea {codigo}", "categoria": "ADMIN"},
        codigo=codigo,
    )
    if tarea.estado != "ACTIVA":  # reparación defensiva entre corridas locales
        tarea.estado = "ACTIVA"
    return tarea


async def obtener_o_crear_permiso(session, codigo: str) -> Permiso:
    return await _get_o_crear(
        session,
        Permiso,
        {"nombre": f"Permiso {codigo}"},
        codigo=codigo,
    )


async def _asegurar_matriz(session, tarea: Tarea, permiso: Permiso) -> None:
    """Garantiza la fila (tarea, permiso) CONCEDIDA en la matriz."""
    fila = await session.get(TareaPermiso, (tarea.id, permiso.id))
    if fila is None:
        session.add(TareaPermiso(tarea_id=tarea.id, permiso_id=permiso.id, concedido=True))
        await session.flush()
    elif not fila.concedido:
        fila.concedido = True


# ============================================================
# FÁBRICAS DE REGISTROS
# ============================================================


async def crear_cadena_rbac(
    session_factory,
    *,
    tareas: tuple[str, ...] | list[str] = (),
    permisos: tuple[str, ...] | list[str] = (),
    estado: str = "ACTIVO",
) -> tuple[Usuario, str]:
    """
    Crea usuario + empleado + asignación VIGENTE de cada tarea y garantiza
    que la matriz `tarea_permiso` conceda cada permiso listado en cada una
    de esas tareas. Devuelve (usuario, CLAVE).

    Con `tareas=()` queda un usuario ACTIVO sin tareas → 403 en cualquier
    endpoint con guard.
    """
    p = prefijo()
    async with session_factory() as session:
        area = await obtener_o_crear_area(session)
        empleado = Empleado(
            rut=f"9{p[:8]}",
            nombres="Prueba",
            apellidos=f"Etapa2 {p[:6]}",
            cargo="Operador",
            area_id=area.id,
            correo=f"emp_{p}@agas.test",
            fecha_ingreso=date(2026, 1, 1),
        )
        session.add(empleado)
        await session.flush()

        user = Usuario(
            username=f"usr_{p}",
            email=f"usr_{p}@agas.test",
            password_hash=hash_password(CLAVE),
            estado=estado,
            requiere_cambio_password=False,
            empleado_id=empleado.id,
        )
        session.add(user)
        await session.flush()

        for codigo_tarea in tareas:
            tarea = await obtener_o_crear_tarea(session, codigo_tarea)
            session.add(
                EmpleadoTarea(
                    empleado_id=empleado.id,
                    tarea_id=tarea.id,
                    usuario_asigno_id=user.id,
                )
            )
            await session.flush()
            for codigo_permiso in permisos:
                permiso = await obtener_o_crear_permiso(session, codigo_permiso)
                await _asegurar_matriz(session, tarea, permiso)

        await session.commit()
        await session.refresh(user)
    return user, CLAVE


async def crear_usuario(session_factory, *, estado: str = "ACTIVO") -> tuple[Usuario, str]:
    """Usuario sin empleado ni tareas (p. ej. dueño de sesiones propias)."""
    p = prefijo()
    async with session_factory() as session:
        user = Usuario(
            username=f"usr_{p}",
            email=f"usr_{p}@agas.test",
            password_hash=hash_password(CLAVE),
            estado=estado,
            requiere_cambio_password=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user, CLAVE


async def crear_empleado(
    session_factory,
    *,
    estado: str = "ACTIVO",
    **campos,
) -> tuple[Empleado, Area]:
    """Empleado único (área fija get-or-create). `campos` sobreescribe defaults."""
    p = prefijo()
    async with session_factory() as session:
        area = await obtener_o_crear_area(session)
        datos = {
            "rut": f"9{p[:8]}",
            "nombres": "Prueba",
            "apellidos": f"Etapa2 {p[:6]}",
            "cargo": "Operador",
            "area_id": area.id,
            "correo": f"emp_{p}@agas.test",
            "fecha_ingreso": date(2026, 1, 1),
            "estado": estado,
        }
        datos.update(campos)
        empleado = Empleado(**datos)
        session.add(empleado)
        await session.commit()
        await session.refresh(empleado)
    return empleado, area


async def crear_tarea_unica(session_factory) -> Tarea:
    """Tarea con código único (para asignar/borrar sin tocar el catálogo fijo)."""
    codigo = f"T{prefijo()[:10]}"
    async with session_factory() as session:
        tarea = await obtener_o_crear_tarea(session, codigo)
        await session.commit()
        await session.refresh(tarea)
    return tarea
