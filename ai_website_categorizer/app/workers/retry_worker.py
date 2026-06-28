import asyncio
import json
import random
import time
from uuid import UUID
from app.core.config import get_settings
from app.core.logger import logger, LoggingContext
from app.database.redis_client import redis_client
from app.database.session import get_db_session
from app.repositories.page_repository import PageRepository
from app.models.page import PageStatus
from app.crawler.frontier import URLFrontier
from app.crawler.url_utils import compute_url_fingerprint
from app.services.page_service import PageService

class RetryWorker:
    def __init__(self, job_id: str, worker_id: str):
        self.job_id = job_id
        self.worker_id = worker_id
        self.settings = get_settings()
        self.queue_key = f"retry_queue:{job_id}"
        self.dead_letter_key = "dead_letter_queue"
        self.max_retries = self.settings.crawler.max_retries

    async def run(self):
        """Worker loop polling the retry queue."""
        with LoggingContext(job_id=self.job_id, worker_id=self.worker_id, phase="RetryWorker"):
            logger.info("Retry worker started")
            
            while True:
                # Update heartbeat
                heartbeat_key = f"worker_heartbeat:retry:{self.worker_id}"
                await redis_client.set_with_ttl(heartbeat_key, str(time.time()), 90)

                raw = await redis_client.pop_from_queue(self.queue_key, timeout=5)
                if not raw:
                    # Check if active jobs list is empty or job complete
                    is_active = await redis_client.client.sismember("active_jobs", self.job_id)
                    if not is_active:
                        logger.info("Job inactive. Retry worker exiting.")
                        break
                    continue
                
                try:
                    item = json.loads(raw)
                    await self._process_retry(item)
                except Exception as e:
                    logger.error(f"Error processing retry item: {e}", exc_info=True)

    async def _process_retry(self, item: dict):
        page_id_str = item["page_id"]
        url = item["url"]
        depth = item["depth"]
        retry_count = item["retry_count"]
        
        logger.info(f"Processing retry for page {page_id_str}. Attempt {retry_count}/{self.max_retries}", page_id=page_id_str)
        
        if retry_count > self.max_retries:
            # Exceeded retries: route to dead letter and mark permanently failed
            logger.error(f"Page {page_id_str} exceeded max retries. Moving to dead letter queue.", page_id=page_id_str)
            await redis_client.push_to_queue(self.dead_letter_key, json.dumps(item))
            
            async with get_db_session() as session:
                page_repo = PageRepository(session)
                page_service = PageService(page_repo)
                await page_service.change_status(UUID(page_id_str), PageStatus.FAILED, {"error": "Max retries exceeded"})
            return

        # Exponential backoff with jitter: delay = base * 2^attempt + jitter
        backoff_base = 2.0
        jitter = random.uniform(0.5, 1.5)
        delay = (backoff_base ** retry_count) * jitter
        delay = min(60.0, delay) # cap delay at 60s
        
        logger.info(f"Sleeping {delay:.2f}s before re-enqueueing {url}", page_id=page_id_str)
        await asyncio.sleep(delay)
        
        # Reset visited fingerprint to allow re-crawl
        fingerprint = compute_url_fingerprint(url)
        await redis_client.client.srem(f"frontier_visited:{self.job_id}", fingerprint)
        
        # Re-queue to URL Frontier
        frontier = URLFrontier(self.job_id)
        await frontier.add_url(url, depth)
        
        # Reset page status back to FETCHING
        async with get_db_session() as session:
            page_repo = PageRepository(session)
            page = await page_repo.get_by_id(UUID(page_id_str))
            if page:
                page.status = PageStatus.FETCHING
                page.retry_count = retry_count
                await session.commit()
                logger.info(f"Re-queued page {page_id_str} back to crawl queue.", page_id=page_id_str)
