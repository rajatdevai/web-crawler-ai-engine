from typing import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.db.url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.app.debug,
)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency injection generator (use with Depends)."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Async context manager for non-FastAPI use (workers, services)."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def check_db_health() -> bool:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
