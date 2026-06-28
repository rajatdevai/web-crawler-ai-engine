import json
from typing import Optional
from app.database.redis_client import redis_client

class CrawlQueue:
    QUEUE_PREFIX = "crawl_queue:"
    RETRY_PREFIX = "retry_queue:"
    DEAD_LETTER = "dead_letter_queue"

    def __init__(self, job_id: str):
        self.job_id = str(job_id)
        self.main_queue = f"{self.QUEUE_PREFIX}{self.job_id}"
        self.retry_queue = f"{self.RETRY_PREFIX}{self.job_id}"

    async def push_url(self, item: dict) -> None:
        """Item should be a dict: {url, job_id, depth, parent_url, discovered_at, retry_count, priority}"""
        payload = json.dumps(item)
        await redis_client.push_to_queue(self.main_queue, payload)

    async def pop_url(self, timeout: int = 5) -> Optional[dict]:
        res = await redis_client.pop_from_queue(self.main_queue, timeout=timeout)
        if res:
            return json.loads(res)
        return None

    async def push_retry(self, item: dict) -> None:
        payload = json.dumps(item)
        await redis_client.push_to_queue(self.retry_queue, payload)

    async def pop_retry(self, timeout: int = 0) -> Optional[dict]:
        res = await redis_client.pop_from_queue(self.retry_queue, timeout=timeout)
        if res:
            return json.loads(res)
        return None

    async def push_dead_letter(self, item: dict) -> None:
        payload = json.dumps(item)
        await redis_client.push_to_queue(self.DEAD_LETTER, payload)

    async def get_queue_depth(self) -> int:
        depth = await redis_client.get_list_length(self.main_queue)
        return depth or 0

    async def clear_queue(self) -> None:
        await redis_client.delete(self.main_queue, self.retry_queue)
