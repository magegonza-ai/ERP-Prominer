"""Esquemas comunes compartidos por todos los módulos (ETAPA 2.1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Pagina[T](BaseModel):
    """Resultado paginado estándar de los listados."""

    items: list[T]
    total: int = Field(description="Total de registros que cumplen el filtro.")
    pagina: int
    por_pagina: int
    paginas: int = Field(description="Total de páginas (ceil(total / por_pagina)).")
