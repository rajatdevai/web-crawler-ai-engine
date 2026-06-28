from typing import AsyncGenerator
from redis.asyncio import Redis, from_url
from app.core.config import Settings, get_settings
from app.core.logger import logger
from app.database.session import get_async_session
from sqlalchemy.ext.asyncio import AsyncSession

async def get_redis_connection() -> AsyncGenerator[Redis, None]:
    settings = get_settings()
    redis = await from_url(settings.redis.url, decode_responses=True)
    try:
        yield redis
    finally:
        await redis.close()

def get_app_logger():
    return logger

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_async_session():
        yield session
