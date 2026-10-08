"""Audit triggers for all audited tables

Revision ID: 0002_audit_triggers
Revises: 0001_initial
Create Date: 2026-10-08

Crea las funciones y triggers de auditoría en las 36 tablas auditadas.
La 0001_initial solo creaba las tablas: una base migrada quedaba SIN
trazabilidad de auditoría (solo create_all, usado en dev/tests, creaba
los triggers).

El DDL vive en app.models.base.generate_audit_trigger (única fuente de
verdad, la misma que dispara on create en create_all). Importar
app.models popula AUDITED_TABLES con los modelos registrados.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from app.models import Base  # noqa: F401  (importa todos los modelos y sus triggers)
from app.models.base import AUDITED_TABLES, generate_audit_trigger

# revision identifiers, used by Alembic.
revision: str = "0002_audit_triggers"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in AUDITED_TABLES:
        for ddl in generate_audit_trigger(table_name):
            # Una sentencia por ejecución: asyncpg/psycopg no aceptan
            # múltiples comandos en una misma sentencia preparada.
            op.execute(str(ddl))


def downgrade() -> None:
    for table_name in AUDITED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS audit_{table_name}_trigger ON {table_name};")
        op.execute(f"DROP FUNCTION IF EXISTS audit_{table_name}_trigger();")
