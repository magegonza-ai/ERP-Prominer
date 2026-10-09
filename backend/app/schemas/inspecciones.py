"""
Esquemas de inspección de cilindros (ETAPA 5.2).

`Inspeccion` es el registro de la inspección técnica de un cilindro: es
**append-only** (POST + GET, sin PATCH/DELETE), `usuario_id` es el usuario
autenticado y `fecha_hora` la fija el servidor. `cilindro_id` es
obligatorio (→ 404 si no existe) y `recepcion_id` un vínculo informativo
opcional con la recepción de origen.

`resultado` (obligatorio) reproduce el `ck_inspeccion_resultado` y mueve el
`estado_operativo` del cilindro vía `Movimiento` (D31): `APTO_LLENADO` →
`APTO_LLENADO`, `REQUIERE_REPARACION` → `APTO_REPARACION`,
`REQUIERE_INSPECCION_TECNICA` → `PENDIENTE_INSPECCION`, `RECHAZADO` →
`RECHAZADO`, `FUERA_SERVICIO` → `FUERA_SERVICIO`.

El checklist (todos opcionales) refleja los `ck_inspeccion_*` del modelo
(`Literal`/`bool` → 422).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Valores permitidos por ck_inspeccion_estado_general.
EstadoGeneral = Literal["BUENO", "REGULAR", "MALO", "CRITICO"]

# Valores permitidos por ck_inspeccion_corrosion.
CorrosionNivel = Literal["NINGUNA", "LEVE", "MODERADA", "SEVERA"]

# Valores permitidos por ck_inspeccion_valvula.
ValvulaEstado = Literal["BUENO", "REGULAR", "MALO", "FALTANTE"]

# Valores permitidos por ck_inspeccion_resultado.
ResultadoInspeccion = Literal[
    "APTO_LLENADO",
    "REQUIERE_REPARACION",
    "REQUIERE_INSPECCION_TECNICA",
    "RECHAZADO",
    "FUERA_SERVICIO",
]


class InspeccionCreate(BaseModel):
    """Alta de inspección (usuario y fecha los deriva el servidor)."""

    cilindro_id: uuid.UUID
    recepcion_id: uuid.UUID | None = None

    # Checklist (todo opcional).
    estado_general: EstadoGeneral | None = None
    pintura_ok: bool | None = None
    corrosion_nivel: CorrosionNivel | None = None
    abolladuras: bool | None = None
    valvula_estado: ValvulaEstado | None = None
    fugas_detectadas: bool | None = None
    serie_legible: bool | None = None
    prueba_hidraulica_vigente: bool | None = None
    gas_compatible: bool | None = None

    resultado: ResultadoInspeccion
    observaciones: str | None = None
    fotografias: dict | None = None


class InspeccionResponse(BaseModel):
    """Respuesta de inspección (espejo del modelo)."""

    id: uuid.UUID
    cilindro_id: uuid.UUID
    recepcion_id: uuid.UUID | None
    usuario_id: uuid.UUID
    fecha_hora: datetime

    estado_general: str | None
    pintura_ok: bool | None
    corrosion_nivel: str | None
    abolladuras: bool | None
    valvula_estado: str | None
    fugas_detectadas: bool | None
    serie_legible: bool | None
    prueba_hidraulica_vigente: bool | None
    gas_compatible: bool | None

    resultado: str
    observaciones: str | None
    fotografias: dict | None
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}
