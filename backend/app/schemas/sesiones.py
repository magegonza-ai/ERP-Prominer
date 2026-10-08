"""Esquemas del módulo de sesiones (ETAPA 2.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SesionResponse(BaseModel):
    """Sesiones (refresh tokens) registradas en la tabla `sesion`."""

    id: uuid.UUID
    usuario_id: uuid.UUID
    usuario_username: str | None = None
    iniciada_en: datetime
    ultima_actividad: datetime
    expira_en: datetime
    revocada: bool
    revocada_en: datetime | None = None
    revocada_por: uuid.UUID | None = None
    ip_inicio: str | None = None
    ip_ultima: str | None = None
    user_agent: str | None = None
