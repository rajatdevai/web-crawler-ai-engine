import time
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from app.core.dependencies import get_db_session, get_redis_connection
from app.database.session import check_db_health
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["Health"])

class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str

class ReadyResponse(BaseModel):
    status: str
    database: str
    redis: str
    queue_reachability: str
    embedding_service: str
    workers: Dict[str, Any]

@router.get("", response_model=HealthResponse)
async def health_check(
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_connection)
):
    db_ok = False
    try:
        db_ok = await check_db_health()
    except Exception:
        pass

    redis_ok = False
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "database": "ok" if db_ok else "degraded",
        "redis": "ok" if redis_ok else "degraded"
    }

@router.get("/ready", response_model=ReadyResponse)
async def readiness_check(
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_connection)
):
    db_status = "ok" if await check_db_health() else "degraded"
    
    redis_status = "degraded"
    queue_reachability = "degraded"
    try:
        await redis.ping()
        redis_status = "ok"
        queue_reachability = "ok"
    except Exception:
        pass

    # Audit all worker heartbeats
    workers_status = {}
    try:
        # Scan for worker_heartbeat:* keys
        async for key in redis.scan_iter("worker_heartbeat:*"):
            val = await redis.get(key)
            if val:
                key_str = key.decode() if isinstance(key, bytes) else key
                val_str = val.decode() if isinstance(val, bytes) else val
                elapsed = time.time() - float(val_str)
                parts = key_str.split(":")
                if len(parts) >= 3:
                    w_type = parts[1]
                    w_id = parts[2]
                    workers_status[f"{w_type}:{w_id}"] = {
                        "status": "ok" if elapsed <= 60 else "stale",
                        "last_seen_seconds_ago": round(elapsed, 1)
                    }
    except Exception as e:
        workers_status["error"] = f"Failed to retrieve worker heartbeats: {e}"

    # General status calculation
    workers_ok = all(w.get("status") == "ok" for w in workers_status.values() if isinstance(w, dict))
    is_healthy = db_status == "ok" and redis_status == "ok" and workers_ok
        
    return {
        "status": "ok" if is_healthy else "degraded",
        "database": db_status,
        "redis": redis_status,
        "queue_reachability": queue_reachability,
        "embedding_service": "ok", # placeholder
        "workers": workers_status
    }
