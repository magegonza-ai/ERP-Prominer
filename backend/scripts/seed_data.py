"""
Datos semilla para el sistema AGAS Cilindros.
Ejecutar después de las migraciones Alembic:
    python -m scripts.seed_data

Carga datos idempotentes (no duplica si ya existen).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, close_db, init_db
from app.models import (
    Area,
    Categoria,
    FormaPago,
    Parametro,
    Permiso,
    Propietario,
    Tarea,
    TareaPermiso,
    TasaImpuesto,
    TipoDocumento,
    TipoGas,
    Ubicacion,
)

# ============================================================
# ÁREAS OPERATIVAS
# ============================================================
AREAS = [
    {"codigo": "RECEP", "nombre": "Recepción", "orden_visual": 1},
    {"codigo": "INSP", "nombre": "Inspección", "orden_visual": 2},
    {"codigo": "LLEN", "nombre": "Área de Llenado", "orden_visual": 3},
    {"codigo": "REP", "nombre": "Área de Reparación", "orden_visual": 4},
    {"codigo": "CAL", "nombre": "Control de Calidad", "orden_visual": 5},
    {"codigo": "DESP", "nombre": "Despacho", "orden_visual": 6},
    {"codigo": "ADM", "nombre": "Administración", "orden_visual": 7},
    {"codigo": "COM", "nombre": "Comercial", "orden_visual": 8},
]

# ============================================================
# TIPOS DE GAS
# ============================================================
TIPOS_GAS = [
    {
        "codigo": "GLP",
        "nombre": "GLP (Gas Licuado de Petróleo)",
        "requiere_prueba_hidraulica": True,
        "color_etiqueta": "#E31E24",
    },
    {"codigo": "GN", "nombre": "Gas Natural", "requiere_prueba_hidraulica": True, "color_etiqueta": "#0066B3"},
    {
        "codigo": "GNI",
        "nombre": "Gas Natural Industrial",
        "requiere_prueba_hidraulica": True,
        "color_etiqueta": "#0066B3",
    },
    {"codigo": "AR", "nombre": "Argón", "requiere_prueba_hidraulica": True, "color_etiqueta": "#00A651"},
    {"codigo": "OX", "nombre": "Oxígeno", "requiere_prueba_hidraulica": True, "color_etiqueta": "#00A651"},
    {"codigo": "N2", "nombre": "Nitrógeno", "requiere_prueba_hidraulica": True, "color_etiqueta": "#F7941D"},
    {"codigo": "CO2", "nombre": "Dióxido de Carbono", "requiere_prueba_hidraulica": True, "color_etiqueta": "#808080"},
    {"codigo": "OTRO", "nombre": "Otro Gas", "requiere_prueba_hidraulica": False, "color_etiqueta": "#808080"},
]

# ============================================================
# UBICACIONES (11 fijas)
# ============================================================
UBICACIONES = [
    {"codigo": "RECEP", "nombre": "Recepción", "tipo": "INTERNA", "orden_visual": 1},
    {"codigo": "ZONA_INSP", "nombre": "Zona de Inspección", "tipo": "INTERNA", "orden_visual": 2},
    {"codigo": "BOD_REC", "nombre": "Bodega de Cilindros Recibidos", "tipo": "INTERNA", "orden_visual": 3},
    {"codigo": "AREA_LLEN", "nombre": "Área de Llenado", "tipo": "INTERNA", "orden_visual": 4},
    {"codigo": "AREA_REP", "nombre": "Área de Reparación", "tipo": "INTERNA", "orden_visual": 5},
    {"codigo": "ZONA_CAL", "nombre": "Zona de Control de Calidad", "tipo": "INTERNA", "orden_visual": 6},
    {"codigo": "BOD_TER", "nombre": "Bodega de Cilindros Terminados", "tipo": "INTERNA", "orden_visual": 7},
    {"codigo": "ZONA_DESP", "nombre": "Zona de Despacho", "tipo": "INTERNA", "orden_visual": 8},
    {"codigo": "CLIENTE", "nombre": "En Cliente", "tipo": "CLIENTE", "permite_entrada": False, "orden_visual": 9},
    {"codigo": "EMP_EXT", "nombre": "Empresa Externa", "tipo": "EXTERNA", "permite_entrada": False, "orden_visual": 10},
    {
        "codigo": "FUERA",
        "nombre": "Fuera de la Empresa",
        "tipo": "FUERA",
        "permite_entrada": False,
        "permite_salida": False,
        "orden_visual": 11,
    },
]

# ============================================================
# FORMAS DE PAGO
# ============================================================
FORMAS_PAGO = [
    {"codigo": "EFEC", "nombre": "Efectivo", "es_tributario": True, "requiere_nro_operacion": False},
    {"codigo": "TRANS", "nombre": "Transferencia", "es_tributario": True, "requiere_nro_operacion": True},
    {"codigo": "DEB", "nombre": "Tarjeta de Débito", "es_tributario": True, "requiere_nro_operacion": True},
    {"codigo": "CRED", "nombre": "Tarjeta de Crédito", "es_tributario": True, "requiere_nro_operacion": True},
    {"codigo": "CRED_CON", "nombre": "Crédito", "es_tributario": False, "requiere_nro_operacion": False},
    {"codigo": "CONVENIO", "nombre": "Convenio", "es_tributario": False, "requiere_nro_operacion": False},
    {"codigo": "VALE", "nombre": "Vale Interno", "es_tributario": False, "requiere_nro_operacion": True},
    {"codigo": "OTRO", "nombre": "Otro", "es_tributario": False, "requiere_nro_operacion": False},
]

# ============================================================
# TIPOS DE DOCUMENTO
# ============================================================
TIPOS_DOCUMENTO = [
    {
        "codigo": "BOLETA",
        "nombre": "Boleta",
        "es_tributario": True,
        "requiere_folio_unico": True,
        "requiere_receptor": True,
        "plantilla_pdf": "boleta.html",
    },
    {
        "codigo": "FACTURA",
        "nombre": "Factura",
        "es_tributario": True,
        "requiere_folio_unico": True,
        "requiere_receptor": True,
        "plantilla_pdf": "factura.html",
    },
    {
        "codigo": "VALE",
        "nombre": "Vale",
        "es_tributario": False,
        "requiere_folio_unico": True,
        "requiere_receptor": True,
        "plantilla_pdf": "vale.html",
    },
    {
        "codigo": "GUIA",
        "nombre": "Guía de Despacho",
        "es_tributario": False,
        "requiere_folio_unico": True,
        "requiere_receptor": True,
        "plantilla_pdf": "guia.html",
    },
    {
        "codigo": "VOUCHER",
        "nombre": "Voucher / Comprobante de Pago",
        "es_tributario": False,
        "requiere_folio_unico": True,
        "requiere_receptor": False,
        "plantilla_pdf": "voucher.html",
    },
    {
        "codigo": "OTRO",
        "nombre": "Otro Documento",
        "es_tributario": False,
        "requiere_folio_unico": True,
        "requiere_receptor": True,
        "plantilla_pdf": "otro.html",
    },
]

# ============================================================
# TASAS DE IMPUESTO
# ============================================================
TASAS_IMPUESTO = [
    {"codigo": "IVA19", "nombre": "IVA 19%", "valor": 19.00, "es_default": True},
    {"codigo": "IVA0", "nombre": "IVA 0% (Exento)", "valor": 0.00, "es_default": False},
    {"codigo": "EXENTO", "nombre": "Exento", "valor": 0.00, "es_default": False},
]

# ============================================================
# TAREAS (30 tareas base)
# ============================================================
TAREAS = [
    {"codigo": "TAREA_01", "nombre": "Registrar clientes", "categoria": "MAESTROS", "es_operativa": False},
    {"codigo": "TAREA_02", "nombre": "Registrar propietarios", "categoria": "MAESTROS", "es_operativa": False},
    {"codigo": "TAREA_03", "nombre": "Registrar cilindros", "categoria": "MAESTROS", "es_operativa": False},
    {"codigo": "TAREA_04", "nombre": "Recibir cilindros", "categoria": "OPERATIVO", "es_operativa": True},
    {
        "codigo": "TAREA_05",
        "nombre": "Inspeccionar cilindros",
        "categoria": "CALIDAD",
        "es_operativa": True,
        "requiere_supervision": True,
    },
    {
        "codigo": "TAREA_06",
        "nombre": "Aprobar cilindros para llenado",
        "categoria": "OPERATIVO",
        "es_operativa": True,
        "requiere_supervision": True,
    },
    {"codigo": "TAREA_07", "nombre": "Crear órdenes de llenado", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_08", "nombre": "Ejecutar llenado", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_09", "nombre": "Cerrar órdenes de llenado", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_10", "nombre": "Crear órdenes de reparación", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_11", "nombre": "Diagnosticar fallas", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_12", "nombre": "Ejecutar reparaciones", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_13", "nombre": "Cerrar órdenes de reparación", "categoria": "OPERATIVO", "es_operativa": True},
    {
        "codigo": "TAREA_14",
        "nombre": "Realizar control de calidad",
        "categoria": "CALIDAD",
        "es_operativa": True,
        "requiere_supervision": True,
    },
    {"codigo": "TAREA_15", "nombre": "Cambiar ubicación", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_16", "nombre": "Registrar movimientos", "categoria": "OPERATIVO", "es_operativa": True},
    {"codigo": "TAREA_17", "nombre": "Preparar entregas", "categoria": "DESPACHO", "es_operativa": True},
    {
        "codigo": "TAREA_18",
        "nombre": "Entregar cilindros",
        "categoria": "DESPACHO",
        "es_operativa": True,
        "requiere_supervision": True,
    },
    {"codigo": "TAREA_19", "nombre": "Registrar devoluciones", "categoria": "DESPACHO", "es_operativa": True},
    {
        "codigo": "TAREA_20",
        "nombre": "Autorizar cambio de propietario",
        "categoria": "ADMIN",
        "es_operativa": False,
        "requiere_supervision": True,
    },
    {"codigo": "TAREA_21", "nombre": "Gestionar productos", "categoria": "COMERCIAL", "es_operativa": False},
    {"codigo": "TAREA_22", "nombre": "Gestionar servicios", "categoria": "COMERCIAL", "es_operativa": False},
    {"codigo": "TAREA_23", "nombre": "Gestionar precios", "categoria": "COMERCIAL", "es_operativa": False},
    {"codigo": "TAREA_24", "nombre": "Gestionar presupuestos", "categoria": "COMERCIAL", "es_operativa": False},
    {"codigo": "TAREA_25", "nombre": "Registrar documentos", "categoria": "COMERCIAL", "es_operativa": False},
    {"codigo": "TAREA_26", "nombre": "Registrar pagos", "categoria": "COMERCIAL", "es_operativa": False},
    {"codigo": "TAREA_27", "nombre": "Generar reportes", "categoria": "REPORTES", "es_operativa": False},
    {
        "codigo": "TAREA_28",
        "nombre": "Administrar usuarios",
        "categoria": "ADMIN",
        "es_operativa": False,
        "requiere_supervision": True,
    },
    {"codigo": "TAREA_29", "nombre": "Administrar catálogos", "categoria": "ADMIN", "es_operativa": False},
    {"codigo": "TAREA_30", "nombre": "Revisar auditoría", "categoria": "AUDITORIA", "es_operativa": False},
]

# ============================================================
# PERMISOS (10 permisos base)
# ============================================================
PERMISOS = [
    {"codigo": "PERM_01", "nombre": "Consultar", "descripcion": "Lectura: listar, ver detalle, exportar"},
    {"codigo": "PERM_02", "nombre": "Crear", "descripcion": "Insertar nuevos registros"},
    {"codigo": "PERM_03", "nombre": "Modificar", "descripcion": "Actualizar registros existentes"},
    {"codigo": "PERM_04", "nombre": "Aprobar", "descripcion": "Cambiar estado a aprobado/validado"},
    {"codigo": "PERM_05", "nombre": "Rechazar", "descripcion": "Cambiar estado a rechazado/observado"},
    {"codigo": "PERM_06", "nombre": "Cerrar", "descripcion": "Finalizar proceso (orden, entrega, presupuesto)"},
    {
        "codigo": "PERM_07",
        "nombre": "Anular",
        "descripcion": "Anular (soft delete) manteniendo historial",
        "es_critico": True,
    },
    {"codigo": "PERM_08", "nombre": "Exportar", "descripcion": "Exportar PDF/Excel/CSV"},
    {"codigo": "PERM_09", "nombre": "Asignar", "descripcion": "Asignar tareas/órdenes a empleados"},
    {
        "codigo": "PERM_10",
        "nombre": "Reasignar",
        "descripcion": "Reasignar tareas ya asignadas (críticas)",
        "es_critico": True,
    },
]

# ============================================================
# MATRIZ TAREA-PERMISO
# Estructura: {codigo_tarea: [indices de permisos (0-based)]}
# Todos tienen CONSULTAR (0). Agregar según operación.
# ============================================================
TAREA_PERMISO_MAP = {
    "TAREA_01": [0, 1, 2, 6, 7],  # Crear clientes
    "TAREA_02": [0, 1, 2, 6, 7],  # Crear propietarios
    "TAREA_03": [0, 1, 2, 6, 7],  # Crear cilindros
    "TAREA_04": [0, 1, 2, 5, 6, 7],  # Recibir cilindros
    "TAREA_05": [0, 1, 2, 3, 4, 5, 7],  # Inspeccionar (aprobar/rechazar)
    "TAREA_06": [0, 3, 4],  # Aprobar para llenado
    "TAREA_07": [0, 1, 2, 6, 7],  # Crear órdenes llenado
    "TAREA_08": [0, 1, 2, 5, 7],  # Ejecutar llenado
    "TAREA_09": [0, 5],  # Cerrar órdenes llenado
    "TAREA_10": [0, 1, 2, 6, 7],  # Crear órdenes reparación
    "TAREA_11": [0, 1, 2, 7],  # Diagnosticar fallas
    "TAREA_12": [0, 1, 2, 5, 7],  # Ejecutar reparaciones
    "TAREA_13": [0, 5],  # Cerrar órdenes reparación
    "TAREA_14": [0, 1, 2, 3, 4, 5, 7],  # Control calidad
    "TAREA_15": [0, 1, 2],  # Cambiar ubicación
    "TAREA_16": [0, 1, 2, 7],  # Registrar movimientos
    "TAREA_17": [0, 1, 2, 5, 7],  # Preparar entregas
    "TAREA_18": [0, 1, 2, 5, 7],  # Entregar cilindros
    "TAREA_19": [0, 1, 2, 7],  # Registrar devoluciones
    "TAREA_20": [0, 3, 4],  # Autorizar cambio propietario
    "TAREA_21": [0, 1, 2, 6, 7],  # Gestionar productos
    "TAREA_22": [0, 1, 2, 6, 7],  # Gestionar servicios
    "TAREA_23": [0, 1, 2, 6, 7],  # Gestionar precios
    "TAREA_24": [0, 1, 2, 3, 4, 5, 6, 7],  # Gestionar presupuestos
    "TAREA_25": [0, 1, 2, 6, 7],  # Registrar documentos
    "TAREA_26": [0, 1, 2, 7],  # Registrar pagos
    "TAREA_27": [0, 7],  # Generar reportes
    "TAREA_28": [0, 1, 2, 6, 7, 8, 9],  # Administrar usuarios (incluye asignar/reasignar)
    "TAREA_29": [0, 1, 2, 6, 7],  # Administrar catálogos
    "TAREA_30": [0, 7],  # Revisar auditoría
}

# ============================================================
# CATEGORÍAS DE PRODUCTOS Y SERVICIOS
# ============================================================
CATEGORIAS = [
    {"tipo": "PRODUCTO", "codigo": "CIL", "nombre": "Cilindro"},
    {"tipo": "PRODUCTO", "codigo": "VAL", "nombre": "Válvula"},
    {"tipo": "PRODUCTO", "codigo": "PRO", "nombre": "Protector"},
    {"tipo": "PRODUCTO", "codigo": "BAS", "nombre": "Base"},
    {"tipo": "PRODUCTO", "codigo": "PIN", "nombre": "Pintura"},
    {"tipo": "PRODUCTO", "codigo": "REP_P", "nombre": "Repuesto"},
    {"tipo": "PRODUCTO", "codigo": "ACC", "nombre": "Accesorio"},
    {"tipo": "PRODUCTO", "codigo": "OTRO_P", "nombre": "Otro Producto"},
    {"tipo": "SERVICIO", "codigo": "S_REC", "nombre": "Recepción"},
    {"tipo": "SERVICIO", "codigo": "S_INS", "nombre": "Inspección"},
    {"tipo": "SERVICIO", "codigo": "S_LLE", "nombre": "Llenado"},
    {"tipo": "SERVICIO", "codigo": "S_REP", "nombre": "Reparación"},
    {"tipo": "SERVICIO", "codigo": "S_MAN", "nombre": "Mantención"},
    {"tipo": "SERVICIO", "codigo": "S_LOG", "nombre": "Logística"},
    {"tipo": "SERVICIO", "codigo": "S_ADM", "nombre": "Administrativo"},
    {"tipo": "SERVICIO", "codigo": "S_OTRO", "nombre": "Otro Servicio"},
]

# ============================================================
# PARÁMETROS DEL SISTEMA
# ============================================================
PARAMETROS = [
    {"clave": "IVA_PORCENTAJE", "valor": "19", "tipo": "DECIMAL", "descripcion": "Porcentaje IVA por defecto"},
    {"clave": "MONEDA_DEFAULT", "valor": "CLP", "tipo": "STRING", "descripcion": "Moneda por defecto"},
    {
        "clave": "REDONDEO_DECIMALES",
        "valor": "0",
        "tipo": "INTEGER",
        "descripcion": "Decimales para redondeo de montos",
    },
    {
        "clave": "TOLERANCIA_DOCUMENTO",
        "valor": "10",
        "tipo": "DECIMAL",
        "descripcion": "Tolerancia en CLP para diferencia documento vs valorización",
    },
    {
        "clave": "DIAS_ALERTA_PRUEBA",
        "valor": "30",
        "tipo": "INTEGER",
        "descripcion": "Días de anticipación para alertar vencimiento prueba hidráulica",
    },
    {
        "clave": "MAX_INTENTOS_LOGIN",
        "valor": "5",
        "tipo": "INTEGER",
        "descripcion": "Intentos fallidos antes de bloquear cuenta",
    },
    {
        "clave": "MINUTOS_BLOQUEO_LOGIN",
        "valor": "30",
        "tipo": "INTEGER",
        "descripcion": "Minutos de bloqueo temporal tras intentos fallidos",
    },
    {
        "clave": "PROPIETARIO_AGAS_RUT",
        "valor": "76.000.000-0",
        "tipo": "STRING",
        "descripcion": "RUT del propietario AGAS institucional",
    },
    {
        "clave": "NOMBRE_EMPRESA",
        "valor": "AGAS",
        "tipo": "STRING",
        "descripcion": "Nombre de la empresa para documentos",
    },
    {
        "clave": "RUT_EMPRESA",
        "valor": "76.000.000-0",
        "tipo": "STRING",
        "descripcion": "RUT de la empresa para documentos (emisor)",
    },
    {"clave": "DIRECCION_EMPRESA", "valor": "Por definir", "tipo": "STRING", "descripcion": "Dirección de la empresa"},
    {"clave": "TELEFONO_EMPRESA", "valor": "", "tipo": "STRING", "descripcion": "Teléfono de la empresa"},
    {
        "clave": "CORREO_EMPRESA",
        "valor": "contacto@agas.cl",
        "tipo": "STRING",
        "descripcion": "Correo de contacto de la empresa",
    },
]


# ============================================================
# FUNCIÓN PRINCIPAL DE CARGA
# ============================================================


async def seed_data() -> None:
    """Carga todos los datos semilla de forma idempotente."""
    print("Iniciando carga de datos semilla...")

    async with async_session_factory() as session:
        # --- ÁREAS ---
        count = await _count(session, Area)
        if count == 0:
            for item in AREAS:
                session.add(Area(**item))
            await session.flush()
            print(f"  ✓ Áreas creadas: {len(AREAS)}")
        else:
            print(f"  - Áreas ya existentes: {count}")

        # --- TIPOS DE GAS ---
        count = await _count(session, TipoGas)
        if count == 0:
            for item in TIPOS_GAS:
                session.add(TipoGas(**item))
            await session.flush()
            print(f"  ✓ Tipos de gas creados: {len(TIPOS_GAS)}")
        else:
            print(f"  - Tipos de gas ya existentes: {count}")

        # --- UBICACIONES ---
        count = await _count(session, Ubicacion)
        if count == 0:
            for item in UBICACIONES:
                session.add(Ubicacion(**item))
            await session.flush()
            print(f"  ✓ Ubicaciones creadas: {len(UBICACIONES)}")
        else:
            print(f"  - Ubicaciones ya existentes: {count}")

        # --- FORMAS DE PAGO ---
        count = await _count(session, FormaPago)
        if count == 0:
            for item in FORMAS_PAGO:
                session.add(FormaPago(**item))
            await session.flush()
            print(f"  ✓ Formas de pago creadas: {len(FORMAS_PAGO)}")
        else:
            print(f"  - Formas de pago ya existentes: {count}")

        # --- TIPOS DE DOCUMENTO ---
        count = await _count(session, TipoDocumento)
        if count == 0:
            for item in TIPOS_DOCUMENTO:
                session.add(TipoDocumento(**item))
            await session.flush()
            print(f"  ✓ Tipos de documento creados: {len(TIPOS_DOCUMENTO)}")
        else:
            print(f"  - Tipos de documento ya existentes: {count}")

        # --- TASAS DE IMPUESTO ---
        count = await _count(session, TasaImpuesto)
        if count == 0:
            for item in TASAS_IMPUESTO:
                session.add(TasaImpuesto(**item))
            await session.flush()
            print(f"  ✓ Tasas de impuesto creadas: {len(TASAS_IMPUESTO)}")
        else:
            print(f"  - Tasas de impuesto ya existentes: {count}")

        # --- CATEGORÍAS ---
        count = await _count(session, Categoria)
        if count == 0:
            for item in CATEGORIAS:
                session.add(Categoria(**item))
            await session.flush()
            print(f"  ✓ Categorías creadas: {len(CATEGORIAS)}")
        else:
            print(f"  - Categorías ya existentes: {count}")

        # --- TAREAS ---
        count = await _count(session, Tarea)
        if count == 0:
            tareas = {}
            for item in TAREAS:
                tarea = Tarea(**item)
                tareas[item["codigo"]] = tarea
                session.add(tarea)
            await session.flush()
            print(f"  ✓ Tareas creadas: {len(TAREAS)}")
        else:
            # Cargar tareas existentes para matriz permisos
            result = await session.execute(select(Tarea))
            tareas = {t.codigo: t for t in result.scalars()}
            print(f"  - Tareas ya existentes: {count}")

        # --- PERMISOS ---
        count = await _count(session, Permiso)
        if count == 0:
            permisos = []
            for item in PERMISOS:
                perm = Permiso(**item)
                permisos.append(perm)
                session.add(perm)
            await session.flush()
            print(f"  ✓ Permisos creados: {len(PERMISOS)}")
        else:
            result = await session.execute(select(Permiso).order_by(Permiso.codigo))
            permisos = list(result.scalars())
            print(f"  - Permisos ya existentes: {count}")

        # --- MATRIZ TAREA-PERMISO ---
        count = await _count(session, TareaPermiso)
        if count == 0:
            perm_by_index = dict(enumerate(permisos))
            tp_count = 0
            for tarea_codigo, perm_indices in TAREA_PERMISO_MAP.items():
                tarea = tareas.get(tarea_codigo)
                if not tarea:
                    continue
                for idx in perm_indices:
                    perm = perm_by_index.get(idx)
                    if perm:
                        session.add(
                            TareaPermiso(
                                tarea_id=tarea.id,
                                permiso_id=perm.id,
                                concedido=True,
                            )
                        )
                        tp_count += 1
            await session.flush()
            print(f"  ✓ Matriz tarea-permiso creada: {tp_count} relaciones")
        else:
            print(f"  - Matriz tarea-permiso ya existe: {count}")

        # --- PARÁMETROS ---
        existing_params = set()
        result = await session.execute(select(Parametro.clave))
        existing_params = {r[0] for r in result}
        param_count = 0
        for item in PARAMETROS:
            if item["clave"] not in existing_params:
                session.add(Parametro(**item))
                param_count += 1
        if param_count > 0:
            await session.flush()
            print(f"  ✓ Parámetros creados: {param_count}")
        else:
            print(f"  - Parámetros ya existentes: {len(existing_params)}")

        # --- PROPIETARIO AGAS (institucional) ---
        result = await session.execute(select(Propietario).where(Propietario.es_institucional_agas.is_(True)))
        agas = result.scalar_one_or_none()
        if not agas:
            agas = Propietario(
                tipo="AGAS",
                razon_social="AGAS - Propietario Institucional",
                rut="76.000.000-0",
                estado="ACTIVO",
                es_institucional_agas=True,
                observaciones="Registro institucional único de AGAS. No eliminar.",
            )
            session.add(agas)
            await session.flush()
            print("  ✓ Propietario AGAS institucional creado")
        else:
            print("  - Propietario AGAS ya existe")

        await session.commit()

    print("\n✅ Carga de datos semilla completada.")


async def _count(session: AsyncSession, model) -> int:
    from sqlalchemy import func

    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar()


async def main() -> None:
    await init_db()
    await seed_data()
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
