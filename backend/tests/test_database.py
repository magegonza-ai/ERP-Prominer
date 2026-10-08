"""
Tests de round-trip contra PostgreSQL real (base de pruebas `agas_cilindros_test`).

Cada test recibe un engine propio (dispose en su propio event loop), evitando
el compartir el engine singleton de la app entre loops de pytest. Si la BD de
pruebas no está disponible, estos tests se omiten (skip); ver conftest.py.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_engine():
    """Engine aislado contra la BD de pruebas + esquema completo (idempotente)."""
    from app.database import create_engine
    from app.models import Base

    engine = create_engine()
    try:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await engine.dispose()
            if os.environ.get("TESTS_REQUIRE_DB") == "1":
                # En CI la BD debe estar: un skip silencioso sería un falso verde.
                pytest.fail(
                    "Base de datos no disponible con TESTS_REQUIRE_DB=1: "
                    "los tests de BD no pueden omitirse en CI"
                )
            pytest.skip("Base de datos de pruebas no disponible (agas_cilindros_test)")

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        await engine.dispose()
        raise

    yield engine

    await engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    """Session factory sobre el engine de pruebas del test actual."""
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def test_esquema_completo_creado(db_engine) -> None:
    from app.models import Base

    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        )
        count_tables = result.scalar()

    assert count_tables >= len(Base.metadata.tables)
    for tabla_critica in ("usuario", "empleado", "area", "cilindro", "orden_trabajo", "detalle_lista_precios"):
        assert tabla_critica in Base.metadata.tables


async def test_crud_de_area_y_unicidad_de_codigo(session_factory) -> None:
    from app.models import Area

    async with session_factory() as session:
        await session.execute(text("DELETE FROM area WHERE codigo = 'TEST_CRUD'"))
        await session.commit()

        # Crear
        area = Area(codigo="TEST_CRUD", nombre="Área de prueba", orden_visual=99)
        session.add(area)
        await session.commit()
        await session.refresh(area)

        assert area.id is not None
        assert area.estado == "ACTIVA"

        # Leer
        found = await session.execute(select(Area).where(Area.codigo == "TEST_CRUD"))
        assert found.scalar_one().nombre == "Área de prueba"

        # Unicidad de código violada
        session.add(Area(codigo="TEST_CRUD", nombre="Duplicada", orden_visual=1))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Limpieza
        await session.execute(text("DELETE FROM area WHERE codigo = 'TEST_CRUD'"))
        await session.commit()

        remaining = await session.execute(select(Area).where(Area.codigo == "TEST_CRUD"))
        assert remaining.scalar_one_or_none() is None


async def test_triggers_de_auditoria_creados(db_engine) -> None:
    """Los triggers de auditoría deben existir en las tablas auditadas registradas."""
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgname LIKE 'audit_%' AND NOT tgisinternal"
            )
        )
        triggers = {row.tgname for row in result.all()}

    for tabla_auditada in ("cliente", "area", "cilindro", "orden_trabajo", "entrega", "usuario"):
        assert f"audit_{tabla_auditada}_trigger" in triggers


async def test_trigger_auditoria_registra_insert_y_delete(session_factory) -> None:
    """Los triggers deben registrar INSERT y DELETE en la tabla auditoría."""

    def query_acciones():  # noqa: ANN202
        return text(
            "SELECT accion FROM auditoria "
            "WHERE valor_nuevo->>'codigo' = 'TEST_AUDIT' "
            "OR valor_anterior->>'codigo' = 'TEST_AUDIT'"
        )

    from app.models import Area

    async with session_factory() as session:
        # Estado limpio
        await session.execute(text("DELETE FROM area WHERE codigo = 'TEST_AUDIT'"))
        await session.execute(
            text(
                "DELETE FROM auditoria "
                "WHERE valor_nuevo->>'codigo' = 'TEST_AUDIT' "
                "OR valor_anterior->>'codigo' = 'TEST_AUDIT'"
            )
        )
        await session.commit()

        # INSERT auditado por el trigger
        session.add(Area(codigo="TEST_AUDIT", nombre="Área auditada", orden_visual=98))
        await session.commit()

        acciones = {row[0] for row in (await session.execute(query_acciones())).all()}
        assert acciones == {"INSERT"}

        # DELETE auditado por el trigger
        await session.execute(text("DELETE FROM area WHERE codigo = 'TEST_AUDIT'"))
        await session.commit()

        acciones = {row[0] for row in (await session.execute(query_acciones())).all()}
        assert acciones == {"INSERT", "DELETE"}

        # Limpieza: la auditoría de la prueba no persiste en la BD de pruebas
        await session.execute(
            text(
                "DELETE FROM auditoria "
                "WHERE valor_nuevo->>'codigo' = 'TEST_AUDIT' "
                "OR valor_anterior->>'codigo' = 'TEST_AUDIT'"
            )
        )
        await session.commit()


async def test_relaciones_orm_configuran_sin_errores() -> None:
    """Las relaciones polimórficas/claras deben configurarse (regresión ORM)."""
    from sqlalchemy.orm import configure_mappers

    from app.models import (
        Area,
        Base,  # noqa: F401
        Cilindro,
        DetalleListaPrecios,
        Entrega,
        OrdenTrabajo,
        Producto,
        Usuario,
    )

    configure_mappers()  # lanza si algún relationship está mal declarado

    assert Area.__tablename__ == "area"
    assert Cilindro.__tablename__ == "cilindro"
    assert Producto.__tablename__ == "producto"
    assert DetalleListaPrecios.__tablename__ == "detalle_lista_precios"
    assert OrdenTrabajo.__tablename__ == "orden_trabajo"
    assert Entrega.__tablename__ == "entrega"
    assert Usuario.__tablename__ == "usuario"
