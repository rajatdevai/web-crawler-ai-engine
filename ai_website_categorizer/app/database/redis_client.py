import time
from typing import Optional, Any
import redis.asyncio as redis
from app.core.config import get_settings
from app.core.logger import logger

class RedisClient:
    def __init__(self):
        self.settings = get_settings()
        self.pool = redis.ConnectionPool.from_url(
            self.settings.redis.url, 
            decode_responses=True,
            max_connections=50,
            protocol=2
        )
        self.client = redis.Redis(connection_pool=self.pool)
        self.circuit_open = False
        self.last_retry_time = 0.0
        self.cooldown_period = 5.0

    async def _safe_execute(self, func, *args, **kwargs) -> Any:
        now = time.time()
        if self.circuit_open:
            if now - self.last_retry_time < self.cooldown_period:
                logger.warning("Redis circuit is open. Bypassing operation.")
                return None
            else:
                logger.info("Redis circuit cooldown expired. Attempting to recover...")
                self.last_retry_time = now
                try:
                    await self.client.ping()
                    self.circuit_open = False
                    logger.info("Redis circuit closed. Connection recovered.")
                except Exception:
                    logger.warning("Redis circuit recovery failed. Keeping circuit open.")
                    return None
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error("Redis connection failed", exc_info=True)
            self.circuit_open = True
            self.last_retry_time = time.time()
            return None

    async def ping(self) -> bool:
        try:
            res = await self.client.ping()
            self.circuit_open = False
            return res
        except Exception:
            self.circuit_open = True
            self.last_retry_time = time.time()
            return False

    async def push_to_queue(self, queue_name: str, item: str) -> Optional[int]:
        return await self._safe_execute(self.client.lpush, queue_name, item)

    async def pop_from_queue(self, queue_name: str, timeout: int = 0) -> Optional[str]:
        res = await self._safe_execute(self.client.brpop, queue_name, timeout=timeout)
        if res:
            return res[1]
        return None

    async def set_with_ttl(self, key: str, value: str, ttl: int) -> bool:
        res = await self._safe_execute(self.client.setex, key, ttl, value)
        return bool(res)

    async def get(self, key: str) -> Optional[str]:
        return await self._safe_execute(self.client.get, key)

    async def delete(self, *keys: str) -> Optional[int]:
        return await self._safe_execute(self.client.delete, *keys)

    async def exists(self, key: str) -> bool:
        res = await self._safe_execute(self.client.exists, key)
        return bool(res)

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        return await self._safe_execute(self.client.incrby, key, amount)

    async def publish(self, channel: str, message: str) -> Optional[int]:
        return await self._safe_execute(self.client.publish, channel, message)

    async def get_list_length(self, queue_name: str) -> Optional[int]:
        return await self._safe_execute(self.client.llen, queue_name)

    async def add_job_event(self, job_id: str, message: str) -> None:
        import json
        from datetime import datetime
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "message": message
        }
        key = f"job_events:{job_id}"
        await self._safe_execute(self.client.rpush, key, json.dumps(event))
        await self._safe_execute(self.client.expire, key, 86400) # expire in 24h

    async def get_job_events(self, job_id: str) -> list:
        key = f"job_events:{job_id}"
        raw_list = await self._safe_execute(self.client.lrange, key, 0, -1)
        if not raw_list:
            return []
        import json
        events = []
        for item in raw_list:
            try:
                events.append(json.loads(item))
            except Exception:
                pass
        return events

redis_client = RedisClient()

