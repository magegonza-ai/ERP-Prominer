"""Initial schema - all tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-07

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # EXTENSIONES
    # ============================================================
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ============================================================
    # CATÁLOGOS MAESTROS
    # ============================================================
    op.create_table(
        "area",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(20), unique=True, nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
        sa.Column("orden_visual", sa.Integer, nullable=False, server_default="0"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "categoria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("codigo", sa.String(20), unique=True, nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("padre_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categoria.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("tipo IN ('PRODUCTO','SERVICIO','AMBOS')", name="ck_categoria_tipo"),
    )

    op.create_table(
        "tipo_gas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(20), unique=True, nullable=False),
        sa.Column("nombre", sa.String(50), nullable=False),
        sa.Column("requiere_prueba_hidraulica", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("color_etiqueta", sa.String(7), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "forma_pago",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(20), unique=True, nullable=False),
        sa.Column("nombre", sa.String(50), nullable=False),
        sa.Column("es_tributario", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("requiere_nro_operacion", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "tipo_documento",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(20), unique=True, nullable=False),
        sa.Column("nombre", sa.String(50), nullable=False),
        sa.Column("es_tributario", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("requiere_folio_unico", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("requiere_receptor", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("plantilla_pdf", sa.String(100), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "parametro",
        sa.Column("clave", sa.String(100), primary_key=True),
        sa.Column("valor", sa.Text, nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("editable", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("actualizada_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("tipo IN ('STRING','INTEGER','DECIMAL','BOOLEAN','JSON','DATE')", name="ck_parametro_tipo"),
    )

    op.create_table(
        "tasa_impuesto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(20), unique=True, nullable=False),
        sa.Column("nombre", sa.String(50), nullable=False),
        sa.Column("valor", sa.Numeric(5, 2), nullable=False),
        sa.Column("es_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("vigencia_desde", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("vigencia_hasta", sa.Date, nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )

    # ============================================================
    # EMPLEADOS, USUARIOS, SESIONES
    # ============================================================
    op.create_table(
        "empleado",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rut", sa.String(12), unique=True, nullable=False),
        sa.Column("nombres", sa.String(100), nullable=False),
        sa.Column("apellidos", sa.String(100), nullable=False),
        sa.Column("cargo", sa.String(100), nullable=False),
        sa.Column("area_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("area.id"), nullable=False),
        sa.Column("correo", sa.String(150), unique=True, nullable=False),
        sa.Column("telefono", sa.String(20), nullable=True),
        sa.Column("fecha_ingreso", sa.Date, nullable=False),
        sa.Column("estado", sa.String(30), nullable=False, server_default="ACTIVO"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('ACTIVO','INACTIVO','SUSPENDIDO','LICENCIA','RETIRADO')", name="ck_empleado_estado"
        ),
    )
    op.create_index("idx_empleado_area_estado", "empleado", ["area_id", "estado"])

    op.create_table(
        "usuario",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "empleado_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("empleado.id"), unique=True, nullable=True
        ),
        sa.Column("username", sa.String(50), unique=True, nullable=False),
        sa.Column("email", sa.String(150), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False, server_default="PENDIENTE_ACTIVACION"),
        sa.Column("requiere_cambio_password", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("totp_secret", sa.String(32), nullable=True),
        sa.Column("totp_activado", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("ultimo_acceso", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intentos_fallidos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('ACTIVO','BLOQUEADO','EXPIRADO','PENDIENTE_ACTIVACION')", name="ck_usuario_estado"
        ),
    )
    op.create_index("idx_usuario_empleado", "usuario", ["empleado_id"])
    op.create_index("idx_usuario_estado", "usuario", ["estado"])

    op.create_table(
        "sesion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip_inicio", postgresql.INET, nullable=True),
        sa.Column("ip_ultima", postgresql.INET, nullable=True),
        sa.Column("iniciada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ultima_actividad", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revocada", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("revocada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocada_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_sesion_usuario_activa", "sesion", ["usuario_id"], postgresql_where=sa.text("NOT revocada"))
    op.create_index("idx_sesion_expira", "sesion", ["expira_en"])

    # ============================================================
    # TAREAS Y PERMISOS
    # ============================================================
    op.create_table(
        "tarea",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(30), unique=True, nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("categoria", sa.String(30), nullable=False),
        sa.Column("es_operativa", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("requiere_supervision", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "categoria IN ('MAESTROS','OPERATIVO','CALIDAD','DESPACHO','COMERCIAL','ADMIN','REPORTES','AUDITORIA')",
            name="ck_tarea_categoria",
        ),
    )

    op.create_table(
        "permiso",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(30), unique=True, nullable=False),
        sa.Column("nombre", sa.String(50), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("es_critico", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "tarea_permiso",
        sa.Column(
            "tarea_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tarea.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "permiso_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("permiso.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("concedido", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "empleado_tarea",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "empleado_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("empleado.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tarea_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tarea.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("fecha_asignacion", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("fecha_inicio", sa.Date, nullable=True),
        sa.Column("fecha_termino", sa.Date, nullable=True),
        sa.Column("usuario_asigno_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="VIGENTE"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado IN ('VIGENTE','VENCIDA','REVOCADA','SUSPENDIDA')", name="ck_empleado_tarea_estado"),
        sa.UniqueConstraint("empleado_id", "tarea_id", "fecha_asignacion", name="uk_empleado_tarea_asignacion"),
    )
    op.create_index(
        "idx_emp_tarea_vigente",
        "empleado_tarea",
        ["empleado_id", "tarea_id"],
        postgresql_where=sa.text("estado='VIGENTE'"),
    )

    # ============================================================
    # CLIENTES Y PROPIETARIOS
    # ============================================================
    op.create_table(
        "cliente",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rut", sa.String(12), unique=True, nullable=False),
        sa.Column("razon_social", sa.String(200), nullable=False),
        sa.Column("direccion", sa.String(300), nullable=True),
        sa.Column("comuna", sa.String(100), nullable=True),
        sa.Column("ciudad", sa.String(100), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("telefono", sa.String(20), nullable=True),
        sa.Column("correo", sa.String(150), nullable=True),
        sa.Column("persona_contacto", sa.String(150), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado IN ('ACTIVO','INACTIVO','BLOQUEADO')", name="ck_cliente_estado"),
    )
    op.create_index("idx_cliente_rut", "cliente", ["rut"])
    op.create_index("idx_cliente_estado", "cliente", ["estado"])

    op.create_table(
        "propietario",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id"), unique=True, nullable=True),
        sa.Column("razon_social", sa.String(200), nullable=False),
        sa.Column("rut", sa.String(12), nullable=False),
        sa.Column("direccion", sa.String(300), nullable=True),
        sa.Column("comuna", sa.String(100), nullable=True),
        sa.Column("ciudad", sa.String(100), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("telefono", sa.String(20), nullable=True),
        sa.Column("correo", sa.String(150), nullable=True),
        sa.Column("persona_contacto", sa.String(150), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("es_institucional_agas", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("tipo IN ('CLIENTE','AGAS','EMPRESA_EXTERNA')", name="ck_propietario_tipo"),
        sa.CheckConstraint("estado IN ('ACTIVO','INACTIVO','BLOQUEADO')", name="ck_propietario_estado"),
    )
    op.create_index("idx_propietario_tipo_estado", "propietario", ["tipo", "estado"])
    op.execute("CREATE UNIQUE INDEX uk_propietario_rut_tipo ON propietario(rut, tipo) WHERE tipo <> 'CLIENTE'")
    op.execute("CREATE UNIQUE INDEX uk_propietario_cliente ON propietario(cliente_id) WHERE cliente_id IS NOT NULL")

    op.create_table(
        "cliente_receptor_autorizado",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "cliente_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("rut", sa.String(12), nullable=True),
        sa.Column("relacion", sa.String(100), nullable=True),
        sa.Column("telefono", sa.String(20), nullable=True),
        sa.Column("correo", sa.String(150), nullable=True),
        sa.Column("autorizado_por", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("fecha_autorizacion", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("vigente_hasta", sa.Date, nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="VIGENTE"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado IN ('VIGENTE','VENCIDO','REVOCADO')", name="ck_receptor_estado"),
    )

    # ============================================================
    # UBICACIONES Y CILINDROS
    # ============================================================
    op.create_table(
        "ubicacion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(30), unique=True, nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("permite_entrada", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("permite_salida", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("orden_visual", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("tipo IN ('INTERNA','CLIENTE','EXTERNA','FUERA')", name="ck_ubicacion_tipo"),
    )

    op.create_table(
        "cilindro",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo_interno", sa.String(30), unique=True, nullable=False),
        sa.Column("numero_serie", sa.String(50), unique=True, nullable=False),
        sa.Column("codigo_qr", sa.String(100), unique=True, nullable=False),
        sa.Column("codigo_barras", sa.String(100), unique=True, nullable=True),
        sa.Column("propietario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("propietario.id"), nullable=False),
        sa.Column("tipo_gas_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tipo_gas.id"), nullable=False),
        sa.Column("capacidad_kg", sa.Numeric(8, 2), nullable=False),
        sa.Column("marca", sa.String(100), nullable=True),
        sa.Column("fabricante", sa.String(100), nullable=True),
        sa.Column("color", sa.String(30), nullable=True),
        sa.Column("fecha_fabricacion", sa.Date, nullable=True),
        sa.Column("fecha_ultima_prueba_hidraulica", sa.Date, nullable=True),
        sa.Column("fecha_vencimiento_prueba", sa.Date, nullable=True),
        sa.Column("estado_operativo", sa.String(30), nullable=False, server_default="REGISTRADO"),
        sa.Column("ubicacion_actual_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ubicacion.id"), nullable=False),
        sa.Column("fotografia_url", sa.String(500), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("estado", sa.String(30), nullable=False, server_default="ACTIVO"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado_operativo IN ("
            "'REGISTRADO','RECIBIDO','PENDIENTE_INSPECCION','APTO_LLENADO',"
            "'ENVIADO_LLENADO','EN_PROCESO_LLENADO','FINALIZADO_LLENADO',"
            "'APTO_REPARACION','ENVIADO_REPARACION','EN_REPARACION','REPARADO',"
            "'PENDIENTE_CONTROL_CALIDAD','APROBADO','APROBADO_OBSERVACIONES',"
            "'LISTO_PARA_ENTREGAR','ENTREGADO','OBSERVADO','RECHAZADO',"
            "'FUERA_SERVICIO','DADO_DE_BAJA')",
            name="ck_cilindro_estado",
        ),
    )
    op.create_index("idx_cilindro_propietario", "cilindro", ["propietario_id"])
    op.create_index("idx_cilindro_estado", "cilindro", ["estado_operativo"])
    op.create_index("idx_cilindro_ubicacion", "cilindro", ["ubicacion_actual_id"])
    op.create_index("idx_cilindro_serie", "cilindro", ["numero_serie"])
    op.execute(
        "CREATE INDEX idx_cilindro_vencimiento_prueba ON cilindro(fecha_vencimiento_prueba) "
        "WHERE estado_operativo NOT IN ('DADO_DE_BAJA','FUERA_SERVICIO')"
    )

    op.create_table(
        "movimiento",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ubicacion_origen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ubicacion.id"), nullable=True),
        sa.Column("ubicacion_destino_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ubicacion.id"), nullable=False),
        sa.Column("estado_anterior", sa.String(30), nullable=False),
        sa.Column("estado_nuevo", sa.String(30), nullable=False),
        sa.Column("usuario_entrega_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("usuario_recibe_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("motivo", sa.String(100), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_movimiento_cilindro_fecha", "movimiento", ["cilindro_id", "fecha_hora"])
    op.create_index("idx_movimiento_fecha", "movimiento", ["fecha_hora"])

    # ============================================================
    # RECEPCIÓN E INSPECCIÓN
    # ============================================================
    op.create_table(
        "recepcion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("numero", sa.String(30), unique=True, nullable=False),
        sa.Column("cliente_entrega_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id"), nullable=False),
        sa.Column("propietario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("propietario.id"), nullable=False),
        sa.Column("cliente_solicita_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id"), nullable=True),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("usuario_responsable_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("documento_referencia", sa.String(100), nullable=True),
        sa.Column("motivo_servicio", sa.String(30), nullable=False),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="COMPLETADA"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "motivo_servicio IN ('LLENADO','REPARACION','INSPECCION','OTRO')", name="ck_recepcion_motivo"
        ),
        sa.CheckConstraint("estado IN ('COMPLETADA','ANULADA')", name="ck_recepcion_estado"),
    )
    op.create_index("idx_recepcion_fecha", "recepcion", ["fecha_hora"])
    op.create_index("idx_recepcion_cliente_entrega", "recepcion", ["cliente_entrega_id"])
    op.create_index("idx_recepcion_propietario", "recepcion", ["propietario_id"])

    op.create_table(
        "detalle_recepcion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "recepcion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recepcion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("estado_fisico", sa.String(20), nullable=False),
        sa.Column("nivel_llenado_pct", sa.Integer, nullable=True),
        sa.Column("accesorios", postgresql.JSONB, nullable=True),
        sa.Column("fotografias", postgresql.JSONB, nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado_fisico IN ('BUENO','REGULAR','MALO','CRITICO')", name="ck_detalle_recepcion_estado"),
        sa.CheckConstraint(
            "nivel_llenado_pct IS NULL OR (nivel_llenado_pct >= 0 AND nivel_llenado_pct <= 100)",
            name="ck_detalle_recepcion_nivel",
        ),
        sa.UniqueConstraint("recepcion_id", "cilindro_id", name="uk_detalle_recepcion_cilindro"),
    )

    op.create_table(
        "inspeccion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recepcion_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recepcion.id"), nullable=True),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("estado_general", sa.String(20), nullable=True),
        sa.Column("pintura_ok", sa.Boolean, nullable=True),
        sa.Column("corrosion_nivel", sa.String(20), nullable=True),
        sa.Column("abolladuras", sa.Boolean, nullable=True),
        sa.Column("valvula_estado", sa.String(20), nullable=True),
        sa.Column("fugas_detectadas", sa.Boolean, nullable=True),
        sa.Column("serie_legible", sa.Boolean, nullable=True),
        sa.Column("prueba_hidraulica_vigente", sa.Boolean, nullable=True),
        sa.Column("gas_compatible", sa.Boolean, nullable=True),
        sa.Column("resultado", sa.String(30), nullable=False),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("fotografias", postgresql.JSONB, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado_general IN ('BUENO','REGULAR','MALO','CRITICO')", name="ck_inspeccion_estado_general"
        ),
        sa.CheckConstraint("corrosion_nivel IN ('NINGUNA','LEVE','MODERADA','SEVERA')", name="ck_inspeccion_corrosion"),
        sa.CheckConstraint("valvula_estado IN ('BUENO','REGULAR','MALO','FALTANTE')", name="ck_inspeccion_valvula"),
        sa.CheckConstraint(
            "resultado IN ('APTO_LLENADO','REQUIERE_REPARACION','REQUIERE_INSPECCION_TECNICA',"
            "'RECHAZADO','FUERA_SERVICIO')",
            name="ck_inspeccion_resultado",
        ),
    )
    op.create_index("idx_inspeccion_cilindro_fecha", "inspeccion", ["cilindro_id", "fecha_hora"])

    # ============================================================
    # ÓRDENES DE TRABAJO Y TAREAS
    # ============================================================
    op.create_table(
        "orden_trabajo",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("numero", sa.String(30), unique=True, nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("area_responsable_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("area.id"), nullable=False),
        sa.Column("usuario_creador_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("usuario_asignado_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("prioridad", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("estado", sa.String(30), nullable=False, server_default="PENDIENTE"),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_estimada_termino", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_termino_real", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resultado", sa.Text, nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("tipo_gas_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tipo_gas.id"), nullable=True),
        sa.Column("tipo_falla", sa.String(50), nullable=True),
        sa.Column("diagnostico", sa.Text, nullable=True),
        sa.Column("trabajo_solicitado", sa.Text, nullable=True),
        sa.Column("estado_registro", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "fecha_creacion_registro", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("tipo IN ('LLENADO','REPARACION','INSPECCION','CALIDAD','ENTREGA')", name="ck_orden_tipo"),
        sa.CheckConstraint("prioridad IN ('NORMAL','URGENTE','EXPRESS')", name="ck_orden_prioridad"),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE','PREPARADA','EN_PROCESO','EN_PAUSA','FINALIZADA',"
            "'PENDIENTE_CALIDAD','APROBADA','RECHAZADA','REQUIERE_NUEVA_REPARACION','CANCELADA')",
            name="ck_orden_estado",
        ),
    )
    op.create_index("idx_orden_tipo_estado", "orden_trabajo", ["tipo", "estado"])
    op.create_index("idx_orden_asignado_fecha", "orden_trabajo", ["usuario_asignado_id", "fecha_creacion"])
    op.execute(
        "CREATE INDEX idx_orden_fecha_estimada ON orden_trabajo(fecha_estimada_termino) "
        "WHERE estado IN ('PENDIENTE','PREPARADA','EN_PROCESO','EN_PAUSA')"
    )

    op.create_table(
        "control_calidad",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "orden_relacionada_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orden_trabajo.id"), nullable=True
        ),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("presion_ok", sa.Boolean, nullable=True),
        sa.Column("peso_ok", sa.Boolean, nullable=True),
        sa.Column("fuga_ok", sa.Boolean, nullable=True),
        sa.Column("etiquetado_ok", sa.Boolean, nullable=True),
        sa.Column("pintura_ok", sa.Boolean, nullable=True),
        sa.Column("accesorios_ok", sa.Boolean, nullable=True),
        sa.Column("documentacion_ok", sa.Boolean, nullable=True),
        sa.Column("resultado", sa.String(30), nullable=False),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("autoriza_entrega", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("fotografias", postgresql.JSONB, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "resultado IN ('APROBADO','APROBADO_OBSERVACIONES','REQUIERE_NUEVA_REPARACION',"
            "'RECHAZADO','PENDIENTE_REVISION')",
            name="ck_control_calidad_resultado",
        ),
    )
    op.create_index("idx_cc_cilindro_fecha", "control_calidad", ["cilindro_id", "fecha_hora"])

    op.create_table(
        "detalle_orden",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "orden_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orden_trabajo.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tipo_gas_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tipo_gas.id"), nullable=True),
        sa.Column("cantidad", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("peso_inicial_kg", sa.Numeric(10, 2), nullable=True),
        sa.Column("peso_final_kg", sa.Numeric(10, 2), nullable=True),
        sa.Column("presion_bar", sa.Numeric(6, 2), nullable=True),
        sa.Column("lote_gas", sa.String(50), nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("orden_id", "cilindro_id", name="uk_detalle_orden_cilindro"),
    )

    op.create_table(
        "tarea_asignada",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "orden_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orden_trabajo.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tarea_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tarea.id"), nullable=False),
        sa.Column("cilindro_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cilindro.id"), nullable=True),
        sa.Column("responsable_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("empleado.id"), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="PENDIENTE"),
        sa.Column("prioridad", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("fecha_asignacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_termino", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_estimada_termino", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resultado", sa.Text, nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("evidencias", postgresql.JSONB, nullable=True),
        sa.Column(
            "reasignada_desde_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tarea_asignada.id"), nullable=True
        ),
        sa.Column("usuario_reasigno_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("fecha_reasignacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_reasignacion", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE','ASIGNADA','EN_PROCESO','EN_PAUSA','COMPLETADA',"
            "'RECHAZADA','CANCELADA','REASIGNADA')",
            name="ck_tarea_asig_estado",
        ),
        sa.CheckConstraint("prioridad IN ('NORMAL','URGENTE','EXPRESS')", name="ck_tarea_asig_prioridad"),
    )
    op.create_index("idx_tarea_asig_responsable_estado", "tarea_asignada", ["responsable_id", "estado"])
    op.create_index("idx_tarea_asig_orden", "tarea_asignada", ["orden_id"])
    op.execute(
        "CREATE INDEX idx_tarea_asig_fecha_estimada ON tarea_asignada(fecha_estimada_termino) "
        "WHERE estado IN ('PENDIENTE','ASIGNADA','EN_PROCESO','EN_PAUSA')"
    )

    # ============================================================
    # PRODUCTOS Y SERVICIOS
    # ============================================================
    op.create_table(
        "producto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(30), unique=True, nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("categoria_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categoria.id"), nullable=False),
        sa.Column("unidad_medida", sa.String(20), nullable=False),
        sa.Column("precio_neto_base", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tasa_impuesto_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasa_impuesto.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("vigencia_desde", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("vigencia_hasta", sa.Date, nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado IN ('ACTIVO','INACTIVO','DESCONTINUADO')", name="ck_producto_estado"),
    )

    op.create_table(
        "servicio",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("codigo", sa.String(30), unique=True, nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("categoria_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categoria.id"), nullable=False),
        sa.Column("unidad_cobro", sa.String(20), nullable=False),
        sa.Column("precio_neto_base", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tasa_impuesto_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasa_impuesto.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("vigencia_desde", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("vigencia_hasta", sa.Date, nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado IN ('ACTIVO','INACTIVO','DESCONTINUADO')", name="ck_servicio_estado"),
    )

    # ============================================================
    # LISTAS DE PRECIOS
    # ============================================================
    op.create_table(
        "lista_precios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("vigencia_desde", sa.Date, nullable=False),
        sa.Column("vigencia_hasta", sa.Date, nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="BORRADOR"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado IN ('BORRADOR','VIGENTE','OBSOLETA','ANULADA')", name="ck_lista_precios_estado"),
    )
    op.create_index("idx_lista_precios_vigencia", "lista_precios", ["vigencia_desde", "vigencia_hasta"])

    op.create_table(
        "detalle_lista_precios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "lista_precios_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lista_precios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entidad_tipo", sa.String(20), nullable=False),
        sa.Column("entidad_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("criterios", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("precio_neto", sa.Numeric(14, 2), nullable=False),
        sa.Column("tasa_impuesto_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasa_impuesto.id"), nullable=True),
        sa.Column("vigencia_desde", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("vigencia_hasta", sa.Date, nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("entidad_tipo IN ('PRODUCTO','SERVICIO')", name="ck_dlp_entidad_tipo"),
        sa.CheckConstraint("estado IN ('ACTIVO','INACTIVO')", name="ck_dlp_estado"),
    )
    op.execute(
        "CREATE INDEX idx_dlp_lista_vigente ON detalle_lista_precios(lista_precios_id, vigencia_desde, vigencia_hasta) "
        "WHERE estado='ACTIVO'"
    )
    op.create_index("idx_dlp_entidad", "detalle_lista_precios", ["entidad_tipo", "entidad_id"])

    # ============================================================
    # PRESUPUESTOS
    # ============================================================
    op.create_table(
        "presupuesto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("numero", sa.String(30), unique=True, nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id"), nullable=False),
        sa.Column("propietario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("propietario.id"), nullable=True),
        sa.Column("fecha", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("fecha_vencimiento", sa.Date, nullable=False),
        sa.Column("usuario_creador_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("usuario_aprobador_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="BORRADOR"),
        sa.Column("neto", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("descuento_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("impuesto_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "presupuesto_original_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("presupuesto.id"), nullable=True
        ),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('BORRADOR','PENDIENTE_APROBACION','APROBADO','RECHAZADO','ANULADO','CONVERTIDO')",
            name="ck_presupuesto_estado",
        ),
    )
    op.create_index("idx_presupuesto_cliente_estado", "presupuesto", ["cliente_id", "estado"])
    op.execute(
        "CREATE INDEX idx_presupuesto_fecha_venc ON presupuesto(fecha_vencimiento) "
        "WHERE estado IN ('BORRADOR','PENDIENTE_APROBACION','APROBADO')"
    )

    op.create_table(
        "detalle_presupuesto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "presupuesto_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("presupuesto.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entidad_tipo", sa.String(20), nullable=False),
        sa.Column("entidad_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("descripcion", sa.String(300), nullable=False),
        sa.Column("cantidad", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("unidad", sa.String(20), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(14, 2), nullable=False),
        sa.Column("descuento_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("descuento_monto", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tasa_impuesto_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("impuesto_monto", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("orden_linea", sa.Integer, nullable=False, server_default="0"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("entidad_tipo IN ('PRODUCTO','SERVICIO')", name="ck_det_presupuesto_entidad_tipo"),
    )

    # ============================================================
    # VALORIZACIÓN
    # ============================================================
    op.create_table(
        "valorizacion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("operacion_tipo", sa.String(30), nullable=False),
        sa.Column("operacion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("neto", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("descuento_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("impuesto_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("estado", sa.String(20), nullable=False, server_default="BORRADOR"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operacion_tipo IN ('RECEPCION','ORDEN_LLENADO','ORDEN_REPARACION','INSPECCION','ENTREGA','PRESUPUESTO')",
            name="ck_valorizacion_operacion_tipo",
        ),
        sa.CheckConstraint("estado IN ('BORRADOR','CALCULADA','VALIDADA','ANULADA')", name="ck_valorizacion_estado"),
    )
    op.create_index("idx_valorizacion_operacion", "valorizacion", ["operacion_tipo", "operacion_id"])
    op.execute(
        "CREATE UNIQUE INDEX uk_valorizacion_operacion ON valorizacion(operacion_tipo, operacion_id) "
        "WHERE estado <> 'ANULADA'"
    )

    op.create_table(
        "detalle_valorizacion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "valorizacion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("valorizacion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entidad_tipo", sa.String(20), nullable=False),
        sa.Column("entidad_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("descripcion", sa.String(300), nullable=False),
        sa.Column("cantidad", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("unidad", sa.String(20), nullable=False),
        sa.Column("precio_unitario_hist", sa.Numeric(14, 2), nullable=False),
        sa.Column("descuento_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("descuento_monto", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tasa_impuesto_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("impuesto_monto", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("orden_linea", sa.Integer, nullable=False, server_default="0"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("entidad_tipo IN ('PRODUCTO','SERVICIO')", name="ck_det_valorizacion_entidad_tipo"),
    )

    # ============================================================
    # DOCUMENTOS COMERCIALES
    # ============================================================
    op.create_table(
        "documento_comercial",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tipo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tipo_documento.id"), nullable=False),
        sa.Column("folio", sa.String(50), nullable=False),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("rut_emisor", sa.String(12), nullable=False),
        sa.Column("nombre_emisor", sa.String(200), nullable=False),
        sa.Column("rut_receptor", sa.String(12), nullable=False),
        sa.Column("nombre_receptor", sa.String(200), nullable=False),
        sa.Column("neto", sa.Numeric(14, 2), nullable=False),
        sa.Column("impuesto", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="CLP"),
        sa.Column("forma_pago_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("forma_pago.id"), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="EMITIDO"),
        sa.Column("adjunto_url", sa.String(500), nullable=True),
        sa.Column("es_tributario", sa.Boolean, nullable=False),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("excepcion_autorizada", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("excepcion_usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("excepcion_fecha", sa.DateTime(timezone=True), nullable=True),
        sa.Column("excepcion_motivo", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('EMITIDO','ANULADO','PAGADO','PENDIENTE_PAGO','PARCIALMENTE_PAGADO')",
            name="ck_documento_estado",
        ),
        sa.UniqueConstraint("tipo_id", "folio", "rut_emisor", name="uk_documento_tipo_folio_emisor"),
    )
    op.create_index("idx_documento_receptor_fecha", "documento_comercial", ["rut_receptor", "fecha"])
    op.execute("CREATE INDEX idx_documento_estado_saldo ON documento_comercial(estado) WHERE total > 0")

    op.create_table(
        "pago",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "documento_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documento_comercial.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("forma_pago_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("forma_pago.id"), nullable=False),
        sa.Column("monto", sa.Numeric(14, 2), nullable=False),
        sa.Column("saldo_pendiente_anterior", sa.Numeric(14, 2), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("numero_operacion", sa.String(100), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="REGISTRADO"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("estado IN ('REGISTRADO','CONFIRMADO','ANULADO','DEVUELTO')", name="ck_pago_estado"),
        sa.CheckConstraint("monto > 0", name="ck_pago_monto_positivo"),
    )
    op.create_index("idx_pago_documento", "pago", ["documento_id"])
    op.create_index("idx_pago_fecha", "pago", ["fecha"])

    # ============================================================
    # ENTREGAS
    # ============================================================
    op.create_table(
        "entrega",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("numero", sa.String(30), unique=True, nullable=False),
        sa.Column("cliente_recibe_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id"), nullable=False),
        sa.Column("propietario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("propietario.id"), nullable=False),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("usuario_responsable_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("receptor_nombre", sa.String(150), nullable=False),
        sa.Column("receptor_rut", sa.String(12), nullable=True),
        sa.Column("receptor_relacion", sa.String(100), nullable=True),
        sa.Column(
            "documento_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documento_comercial.id"), nullable=True
        ),
        sa.Column("firma_confirmacion_url", sa.String(500), nullable=True),
        sa.Column("firma_tipo", sa.String(20), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="BORRADOR"),
        sa.Column("excepcion_documento", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("excepcion_usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("excepcion_fecha", sa.DateTime(timezone=True), nullable=True),
        sa.Column("excepcion_motivo", sa.Text, nullable=True),
        sa.Column(
            "valorizacion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("valorizacion.id"),
            unique=True,
            nullable=True,
        ),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('BORRADOR','PENDIENTE','CONFIRMADA','ENTREGADA','CANCELADA','EXCEPCION_DOC')",
            name="ck_entrega_estado",
        ),
        sa.CheckConstraint(
            "firma_tipo IS NULL OR firma_tipo IN ('DIGITAL','FOTO_MANUSCRITA','HUELLA','OTRO')",
            name="ck_entrega_firma_tipo",
        ),
    )
    op.create_index("idx_entrega_fecha", "entrega", ["fecha_hora"])
    op.create_index("idx_entrega_cliente", "entrega", ["cliente_recibe_id"])
    op.create_index("idx_entrega_estado", "entrega", ["estado"])

    op.create_table(
        "detalle_entrega",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "entrega_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entrega.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entidad_tipo", sa.String(20), nullable=True),
        sa.Column("entidad_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cantidad", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("precio_unitario", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("descuento_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("descuento_monto", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tasa_impuesto_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("impuesto_monto", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("entrega_id", "cilindro_id", name="uk_detalle_entrega_cilindro"),
        sa.CheckConstraint(
            "entidad_tipo IS NULL OR entidad_tipo IN ('PRODUCTO','SERVICIO')",
            name="ck_detalle_entrega_entidad_tipo",
        ),
    )

    # ============================================================
    # CAMBIO DE PROPIETARIO
    # ============================================================
    op.create_table(
        "cambio_propietario",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "propietario_anterior_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("propietario.id"), nullable=False
        ),
        sa.Column(
            "propietario_nuevo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("propietario.id"), nullable=False
        ),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("usuario_autoriza_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False),
        sa.Column("motivo", sa.String(200), nullable=False),
        sa.Column("documento_respaldo_url", sa.String(500), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_cambio_prop_cilindro_fecha", "cambio_propietario", ["cilindro_id", "fecha"])

    # ============================================================
    # AUDITORÍA Y TRANSVERSALES
    # ============================================================
    op.create_table(
        "auditoria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modulo", sa.String(50), nullable=False),
        sa.Column("accion", sa.String(30), nullable=False),
        sa.Column("registro_afectado_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("registro_tipo", sa.String(50), nullable=True),
        sa.Column("valor_anterior", postgresql.JSONB, nullable=True),
        sa.Column("valor_nuevo", postgresql.JSONB, nullable=True),
        sa.Column("motivo", sa.Text, nullable=True),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.CheckConstraint(
            "accion IN ('INSERT','UPDATE','DELETE','LOGIN','LOGOUT','EXPORT','IMPORT',"
            "'EXCEPCION','REASIGNAR','APROBAR','RECHAZAR','CAMBIO_ESTADO')",
            name="ck_auditoria_accion",
        ),
    )
    op.create_index("idx_auditoria_usuario_fecha", "auditoria", ["usuario_id", "fecha_hora"])
    op.create_index("idx_auditoria_registro", "auditoria", ["registro_tipo", "registro_afectado_id"])
    op.create_index("idx_auditoria_fecha", "auditoria", ["fecha_hora"])

    op.create_table(
        "fotografia",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entidad_tipo", sa.String(50), nullable=False),
        sa.Column("entidad_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("descripcion", sa.String(300), nullable=True),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("es_principal", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_foto_entidad", "fotografia", ["entidad_tipo", "entidad_id"])

    op.create_table(
        "documento_adjunto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entidad_tipo", sa.String(50), nullable=False),
        sa.Column("entidad_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tipo_documento", sa.String(50), nullable=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("nombre_original", sa.String(255), nullable=True),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_doc_adjunto_entidad", "documento_adjunto", ["entidad_tipo", "entidad_id"])

    op.create_table(
        "notificacion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "usuario_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("titulo", sa.String(200), nullable=False),
        sa.Column("mensaje", sa.Text, nullable=False),
        sa.Column("leida", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("entidad_relacionada_tipo", sa.String(50), nullable=True),
        sa.Column("entidad_relacionada_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prioridad", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("accion_url", sa.String(500), nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("prioridad IN ('BAJA','NORMAL','ALTA','CRITICA')", name="ck_notificacion_prioridad"),
    )
    op.create_index("idx_notif_usuario_leida", "notificacion", ["usuario_id", "leida", "fecha_hora"])


def downgrade() -> None:
    op.drop_table("notificacion")
    op.drop_table("documento_adjunto")
    op.drop_table("fotografia")
    op.drop_table("auditoria")
    op.drop_table("cambio_propietario")
    op.drop_table("detalle_entrega")
    op.drop_table("entrega")
    op.drop_table("pago")
    op.drop_table("documento_comercial")
    op.drop_table("detalle_valorizacion")
    op.drop_table("valorizacion")
    op.drop_table("detalle_presupuesto")
    op.drop_table("presupuesto")
    op.drop_table("detalle_lista_precios")
    op.drop_table("lista_precios")
    op.drop_table("servicio")
    op.drop_table("producto")
    op.drop_table("tarea_asignada")
    op.drop_table("detalle_orden")
    op.drop_table("control_calidad")
    op.drop_table("orden_trabajo")
    op.drop_table("inspeccion")
    op.drop_table("detalle_recepcion")
    op.drop_table("recepcion")
    op.drop_table("movimiento")
    op.drop_table("cilindro")
    op.drop_table("ubicacion")
    op.drop_table("cliente_receptor_autorizado")
    op.drop_table("propietario")
    op.drop_table("cliente")
    op.drop_table("empleado_tarea")
    op.drop_table("tarea_permiso")
    op.drop_table("permiso")
    op.drop_table("tarea")
    op.drop_table("sesion")
    op.drop_table("usuario")
    op.drop_table("empleado")
    op.drop_table("tasa_impuesto")
    op.drop_table("parametro")
    op.drop_table("tipo_documento")
    op.drop_table("forma_pago")
    op.drop_table("tipo_gas")
    op.drop_table("categoria")
    op.drop_table("area")
