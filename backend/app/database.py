"""
Configuración de base de datos asíncrona con SQLAlchemy 2.0.
Incluye engine, session factory y utilidades para health checks.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# ============================================================
# ENGINE CONFIGURATION
# ============================================================


def create_engine() -> AsyncEngine:
    """Crea el engine asíncrono con configuración optimizada."""
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT,
        pool_pre_ping=True,  # Verifica conexiones antes de usar
        echo=settings.DATABASE_ECHO,
        # Configuración para producción
        connect_args={
            "server_settings": {
                "application_name": "agas-cilindros-api",
                "jit": "off",  # Desactivar JIT para queries cortas
                "timezone": "America/Santiago",
            },
            "command_timeout": 60,
        },
    )
    return engine


# Engine singleton
engine: AsyncEngine = create_engine()

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ============================================================
# DEPENDENCY INJECTION
# ============================================================


async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    Dependency para FastAPI que provee una sesión de BD por request.
    Maneja commit/rollback automático y cierre de sesión.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_readonly() -> AsyncGenerator[AsyncSession]:
    """Sesión de solo lectura para consultas que no modifican datos."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================================
# HEALTH CHECKS & UTILITIES
# ============================================================


async def check_database_connection() -> bool:
    """Verifica conectividad a la base de datos."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception:
        return False


async def get_database_version() -> str | None:
    """Obtiene versión de PostgreSQL."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            return result.scalar()
    except Exception:
        return None


async def init_db() -> None:
    """
    Inicializa la base de datos.
    En desarrollo: crea tablas si no existen.
    En producción: usa Alembic migrations.
    """
    if settings.ENVIRONMENT == "development":
        # Import models to register them
        from app.models import Base  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Cierra el engine y libera conexiones."""
    await engine.dispose()


# ============================================================
# EVENT LISTENERS (para logging de queries lentas, etc.)
# ============================================================


@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start_time", []).append(__import__("time").time())


@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = __import__("time").time() - conn.info["query_start_time"].pop(-1)
    if total > 1.0:  # Log queries > 1 second
        import structlog

        logger = structlog.get_logger("database.slow_query")
        logger.warning(
            "slow_query_detected",
            duration_ms=round(total * 1000, 2),
            statement=statement[:500],
        )


# ============================================================
# TRANSACTION HELPERS
# ============================================================


@asynccontextmanager
async def transaction(session: AsyncSession):
    """
    Context manager para transacciones explícitas.
    Uso:
        async with transaction(db) as tx:
            await tx.execute(...)
    """
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise


class DatabaseManager:
    """Helper para operaciones de mantenimiento de BD."""

    @staticmethod
    async def vacuum_analyze() -> None:
        """Ejecuta VACUUM ANALYZE (requiere autocommit)."""
        async with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            await conn.execute(text("VACUUM ANALYZE"))

    @staticmethod
    async def get_table_sizes() -> list:
        """Retorna tamaños de tablas principales."""
        query = text("""
            SELECT
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
                pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY size_bytes DESC
        """)
        async with engine.connect() as conn:
            result = await conn.execute(query)
            return result.mappings().all()

    @staticmethod
    async def get_index_usage() -> list:
        """Retorna estadísticas de uso de índices."""
        query = text("""
            SELECT
                schemaname,
                tablename,
                indexname,
                idx_scan,
                idx_tup_read,
                idx_tup_fetch
            FROM pg_stat_user_indexes
            WHERE schemaname = 'public'
            ORDER BY idx_scan DESC
        """)
        async with engine.connect() as conn:
            result = await conn.execute(query)
            return result.mappings().all()
