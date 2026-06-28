import urllib.parse
from typing import Optional, List
from app.database.redis_client import redis_client
from app.crawler.url_utils import compute_url_fingerprint
from app.core.logger import logger

class URLFrontier:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.queue_key = f"frontier_queue:{job_id}"
        self.visited_key = f"frontier_visited:{job_id}"
        
    async def add_url(self, url: str, depth: int, is_sitemap: bool = False, parent_url: Optional[str] = None) -> bool:
        """Adds URL to frontier if not visited. Returns True if added."""
        fingerprint = compute_url_fingerprint(url)
        
        # Atomic check-and-add to completely prevent concurrent duplicate queue schedules
        added = await redis_client.client.sadd(self.visited_key, fingerprint)
        if not added:
            return False

        score = self._calculate_priority(url, depth, is_sitemap)
        
        # Add to sorted set
        # Payload can just be the URL, or we can store JSON. Let's store a simple formatted string: depth|url
        # Or better, we can just push the dict to the CrawlQueue if we were using it, but the prompt says:
        # "Implement app/crawler/frontier.py as a priority queue backed by Redis sorted sets... 
        # The visited set must be persisted in Redis as a set... add_url, mark_visited, is_visited..."
        
        payload = f"{depth}|{parent_url or ''}|{url}"
        await redis_client.client.zadd(self.queue_key, {payload: score})
        return True

    async def add_urls_bulk(self, urls: List[str], depth: int, is_sitemap: bool = False, parent_url: Optional[str] = None) -> int:
        added_count = 0
        for url in urls:
            if await self.add_url(url, depth, is_sitemap, parent_url):
                added_count += 1
        return added_count

    async def get_next_url(self) -> Optional[dict]:
        """Pops the highest priority URL from the sorted set."""
        # ZPOPMAX removes and returns the highest score
        res = await redis_client.client.zpopmax(self.queue_key, count=1)
        if not res:
            return None
            
        payload, _score = res[0]
        # payload format: depth|parent_url|url
        parts = payload.split("|", 2)
        if len(parts) == 3:
            return {
                "depth": int(parts[0]),
                "parent_url": parts[1] if parts[1] else None,
                "url": parts[2]
            }
        return None

    def _calculate_priority(self, url: str, depth: int, is_sitemap: bool) -> float:
        """
        Calculates priority score (higher is popped first).
        Base score is 1000.
        Sitemap URLs get +500.
        Shallow URLs get + (100 - depth * 10).
        Content paths get +100. Utility paths get -200.
        """
        score = 1000.0
        if is_sitemap:
            score += 500.0
            
        # Depth penalty (shallow is better)
        score += max(0, 100 - (depth * 10))
        
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.lower()
        
        # Content rich paths
        if any(p in path for p in ["/blog", "/products", "/services", "/article", "/guide"]):
            score += 100.0
            
        # Utility paths
        if any(p in path for p in ["/login", "/cart", "/checkout", "/account", "/password", "/tags", "/author"]):
            score -= 200.0
            
        return score

    async def get_queue_size(self) -> int:
        return await redis_client.client.zcard(self.queue_key) or 0

    async def is_visited(self, url: str) -> bool:
        fingerprint = compute_url_fingerprint(url)
        return bool(await redis_client.client.sismember(self.visited_key, fingerprint))

    async def mark_visited(self, url: str) -> None:
        fingerprint = compute_url_fingerprint(url)
        await redis_client.client.sadd(self.visited_key, fingerprint)
