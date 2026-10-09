"""Devoluciones de cilindros (ETAPA 5.6) - tablas devolucion y detalle_devolucion

Revision ID: 0004_devolucion
Revises: 41a726a07104
Create Date: 2026-10-09

La ETAPA 5.6 introduce el flujo inverso de la entrega: cilindros `ENTREGADO`
que el cliente devuelve a AGAS. No existía tabla en la 0001_initial (a
diferencia de `entrega`), por lo que además de crear las tablas hay que
registrar sus triggers de auditoría (misma función que 0002, única fuente de
verdad en app.models.base.generate_audit_trigger).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.base import generate_audit_trigger

# revision identifiers, used by Alembic.
revision: str = "0004_devolucion"
down_revision: Union[str, None] = "41a726a07104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # DEVOLUCION (cabecera)
    # ============================================================
    op.create_table(
        "devolucion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("numero", sa.String(30), nullable=False, unique=True),
        sa.Column(
            "cliente_devuelve_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cliente.id"), nullable=False
        ),
        sa.Column("entrega_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entrega.id"), nullable=True),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "usuario_responsable_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("usuario.id"), nullable=False
        ),
        sa.Column("motivo", sa.String(30), nullable=False),
        sa.Column("documento_referencia", sa.String(100), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column(
            "ubicacion_destino_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ubicacion.id"), nullable=True
        ),
        sa.Column("estado", sa.String(20), nullable=False, server_default="REGISTRADA"),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "motivo IN ('DEVOLUCION_CLIENTE','DANO_EN_TRANSITO','ERROR_ENTREGA','GARANTIA','OTRO')",
            name="ck_devolucion_motivo",
        ),
        sa.CheckConstraint("estado IN ('REGISTRADA','ANULADA')", name="ck_devolucion_estado"),
    )
    op.create_index("idx_devolucion_fecha", "devolucion", ["fecha_hora"])
    op.create_index("idx_devolucion_cliente", "devolucion", ["cliente_devuelve_id"])
    op.create_index("idx_devolucion_estado", "devolucion", ["estado"])

    # ============================================================
    # DETALLE_DEVOLUCION (cilindros devueltos)
    # ============================================================
    op.create_table(
        "detalle_devolucion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "devolucion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devolucion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cilindro_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cilindro.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("estado_fisico", sa.String(20), nullable=False),
        sa.Column("accesorios", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("devolucion_id", "cilindro_id", name="uk_detalle_devolucion_cilindro"),
        sa.CheckConstraint(
            "estado_fisico IN ('BUENO','REGULAR','MALO','CRITICO')",
            name="ck_detalle_devolucion_estado",
        ),
    )

    # ============================================================
    # TRIGGERS DE AUDITORÍA (autogenerados por el modelo, como 0002)
    # ============================================================
    for table_name in ("devolucion", "detalle_devolucion"):
        for ddl in generate_audit_trigger(table_name):
            # Una sentencia por ejecución: asyncpg/psycopg no aceptan
            # múltiples comandos en una misma sentencia preparada.
            op.execute(str(ddl))


def downgrade() -> None:
    for table_name in ("devolucion", "detalle_devolucion"):
        op.execute(f"DROP TRIGGER IF EXISTS audit_{table_name}_trigger ON {table_name};")
        op.execute(f"DROP FUNCTION IF EXISTS audit_{table_name}_trigger();")

    op.drop_table("detalle_devolucion")
    op.drop_table("devolucion")
