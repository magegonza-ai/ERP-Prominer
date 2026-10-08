"""Esquemas del módulo de auditoría (solo lectura, ETAPA 2.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditoriaResponse(BaseModel):
    """Fila de la tabla inmutable `auditoria` (escrita por triggers)."""

    id: uuid.UUID
    usuario_id: uuid.UUID | None = None
    fecha_hora: datetime
    modulo: str
    accion: str
    registro_afectado_id: uuid.UUID | None = None
    registro_tipo: str | None = None
    valor_anterior: dict[str, Any] | None = None
    valor_nuevo: dict[str, Any] | None = None
    motivo: str | None = None
    ip: str | None = None
    user_agent: str | None = None
