"""
Generación de correlativos legibles para documentos operativos (ETAPA 5, D30).

Los documentos de la ETAPA 5 (recepción, órdenes de trabajo) llevan un
`numero` único que **genera el servidor** con el formato
``<PREFIJO>-<AÑO>-######`` (p. ej. ``REC-2026-000123``). El consecutivo es
por prefijo y por año natural (UTC).

`pg_advisory_xact_lock` serializa la generación del mismo prefijo dentro de
la transacción (se libera al hacer *commit*), de modo que dos peticiones
concurrentes nunca obtienen el mismo número; el `UNIQUE` del modelo es la
última red de seguridad.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


async def siguiente_numero(session: AsyncSession, model, campo: str, prefijo: str) -> str:
    """
    Devuelve el siguiente correlativo ``<PREFIJO>-<AÑO>-######`` para
    ``model.campo`` (columna de texto con valores únicos).

    El consecutivo se calcula sobre los registros existentes del año en
    curso con ese prefijo; el ancho fijo (6 dígitos) mantiene el orden
    legible y estable.
    """
    base = f"{prefijo}-{datetime.now(UTC).year}-"

    # Serializa la generación del mismo prefijo en la transacción actual.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:clave))").bindparams(clave=base)
    )

    columna = getattr(model, campo)
    valores = (
        await session.execute(select(columna).where(columna.like(f"{base}%")))
    ).scalars().all()

    consecutivo = 0
    for valor in valores:
        sufijo = valor.rsplit("-", 1)[-1]
        if sufijo.isdigit():
            consecutivo = max(consecutivo, int(sufijo))

    return f"{base}{consecutivo + 1:06d}"
