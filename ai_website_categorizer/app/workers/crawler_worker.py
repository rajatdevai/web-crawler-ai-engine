import asyncio
import time
import httpx
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from uuid import UUID

from app.core.logger import logger, LoggingContext
from app.core.config import get_settings
from app.crawler.frontier import URLFrontier
from app.crawler.url_utils import normalize_url, is_internal_url, extract_domain, is_crawlable_url
from app.crawler.robots import RobotsTxtParser
from app.services.page_service import PageService
from app.models.page import PageStatus, Page
from app.repositories.page_repository import PageRepository
from app.renderers import RendererFactory
from app.database.redis_client import redis_client

class CrawlerWorker:
    def __init__(self, job_id: UUID, seed_url: str, page_service: PageService, robots_parser: RobotsTxtParser, renderer_factory: RendererFactory, allowed_path_prefix: Optional[str] = None):
        self.job_id = job_id
        self.seed_url = seed_url
        self.settings = get_settings()
        self.frontier = URLFrontier(str(job_id))
        self.page_service = page_service
        self.robots_parser = robots_parser
        self.renderer_factory = renderer_factory
        self.domain = extract_domain(seed_url)
        self.allowed_path_prefix = allowed_path_prefix

    async def run(self):
        """Worker loop pulling from frontier."""
        worker_id = f"worker-{id(self)}"
        with LoggingContext(job_id=str(self.job_id), worker_id=worker_id, phase="WorkerLoop"):
            logger.info("Worker started")
            
            while True:
                item = await self.frontier.get_next_url()
                if not item:
                    # Queue is empty, wait a bit before exiting or checking again
                    await asyncio.sleep(2)
                    # Check again to avoid race conditions
                    if await self.frontier.get_queue_size() == 0:
                        break
                    continue
                
                url = item["url"]
                depth = item["depth"]
                parent_url = item["parent_url"]
                
                await self._process_url(url, depth, parent_url)
                
            logger.info("Worker finished (frontier empty)")

    async def _process_url(self, url: str, depth: int, parent_url: Optional[str]):
        """Processes a single URL."""
        with LoggingContext(job_id=str(self.job_id), phase="ProcessURL"):
            if depth > self.settings.crawler.max_depth:
                logger.debug(f"Skipping {url} (max depth exceeded)")
                return

            if not self.robots_parser.is_allowed(url):
                logger.info(f"Skipping {url} (blocked by robots.txt)")
                return

            # Rate Limiting
            await self._enforce_rate_limit()

            # Page State: DISCOVERED -> FETCHING
            # In a real system, Page object would be created in DB here if not exists
            if self.allowed_path_prefix:
                from urllib.parse import urlparse as parse_url
                if not parse_url(url).path.startswith(self.allowed_path_prefix):
                    logger.info(f"Skipping {url} (does not match prefix '{self.allowed_path_prefix}')")
                    return

            await redis_client.add_job_event(str(self.job_id), f"🕷️ Spawning dynamic renderer for: {url}")
            page_record = Page(job_id=self.job_id, url=url, depth=depth, status=PageStatus.FETCHING)
            await self.page_service.repository.create(page_record)
            await self.page_service.repository.session.commit()
            page_id = page_record.id

            try:
                # Use Renderer Factory
                render_result = await self.renderer_factory.render_adaptive(url)
                
                if render_result.error:
                    await redis_client.add_job_event(str(self.job_id), f"❌ Failed to fetch page {url}: {render_result.error}")
                    await self.page_service.change_status(page_id, PageStatus.FAILED, {"error": render_result.error})
                    await self.page_service.repository.session.commit()
                    return
                    
                # Update state using secure parameterized query to prevent any SQL injection warning
                from sqlalchemy import text
                await self.page_service.repository.session.execute(
                    text("UPDATE pages SET render_method = :method, http_status = :status WHERE id = :id"),
                    {
                        "method": render_result.render_method.value,
                        "status": render_result.http_status,
                        "id": page_id
                    }
                )
                await self.page_service.change_status(page_id, PageStatus.FETCHED)
                await redis_client.add_job_event(str(self.job_id), f"📄 Successfully retrieved page {url} (HTTP {render_result.http_status})")

                # Use ExtractionService to run the full extraction pipeline
                await redis_client.add_job_event(str(self.job_id), f"🧩 Extracting main article text and metadata from {url}")
                from app.services.extraction_service import ExtractionService
                extraction_service = ExtractionService(
                    session=self.page_service.repository.session,
                    page_service=self.page_service,
                    seed_url=self.seed_url
                )
                success = await extraction_service.process(page_id, render_result, str(self.job_id))
                if not success:
                    await redis_client.add_job_event(str(self.job_id), f"❌ Failed to extract content from {url}")
                    return

                # Retrieve links from page_document after extraction and queue them
                page = await self.page_service.repository.get_by_id(page_id)
                if page and page.page_document:
                    discovered_count = 0
                    for link in page.page_document.get("internal_links", []):
                        if is_crawlable_url(link) and is_internal_url(link, self.seed_url):
                            if self.allowed_path_prefix:
                                from urllib.parse import urlparse as parse_url
                                if not parse_url(link).path.startswith(self.allowed_path_prefix):
                                    continue
                            added = await self.frontier.add_url(link, depth + 1, parent_url=url)
                            if added:
                                discovered_count += 1
                    if discovered_count > 0:
                        await redis_client.add_job_event(str(self.job_id), f"🔗 Discovered {discovered_count} new section links on {url}")
                
            except Exception as e:
                logger.error(f"Unexpected error processing {url}: {e}", exc_info=True)
                await redis_client.add_job_event(str(self.job_id), f"❌ Error processing {url}: {e}")
                await self.page_service.change_status(page_id, PageStatus.FAILED, {"error": str(e)})
                await self.page_service.repository.session.commit()

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            norm_url = normalize_url(href, base_url)
            if is_crawlable_url(norm_url) and is_internal_url(norm_url, self.seed_url):
                links.append(norm_url)
        return list(set(links))

    async def _enforce_rate_limit(self):
        # Determine delay
        delay = self.settings.crawler.domain_rate_limits.get(self.domain, self.settings.crawler.crawl_delay)
        
        # Using Redis to track last request time for the domain
        key = f"rate_limit:{self.domain}"
        now = time.time()
        
        # Atomically get and set new time
        # This is a simplistic semaphore/rate limiter. For enterprise, use token bucket.
        last_req = await redis_client.get(key)
        if last_req:
            elapsed = now - float(last_req)
            if elapsed < delay:
                sleep_time = delay - elapsed
                logger.debug(f"Rate limiting domain {self.domain}: sleeping {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
                
        await redis_client.set_with_ttl(key, str(time.time()), int(delay * 2) + 1)

if __name__ == "__main__":
    import json
    
    async def main():
        from app.database.session import get_db_session
        from app.repositories.job_repository import JobRepository
        from app.repositories.page_repository import PageRepository
        from app.services.job_service import JobService
        from app.services.page_service import PageService
        from app.crawler.orchestrator import CrawlerOrchestrator
        from app.workers.embedding_worker import EmbeddingWorker
        from app.workers.categorization_worker import CategorizationWorker
        from app.database.redis_client import redis_client

        logger.info("Crawler coordinator daemon starting...")
        
        while True:
            try:
                # Poll for job start events from Redis
                raw = await redis_client.pop_from_queue("job_start_queue", timeout=5)
                if not raw:
                    continue

                event = json.loads(raw)
                job_id_str = event["job_id"]
                url = event["url"]
                job_uuid = UUID(job_id_str)
                
                logger.info("Found job to process in queue", job_id=job_id_str, url=url)
                
                async with get_db_session() as session:
                    job_repo = JobRepository(session)
                    page_repo = PageRepository(session)
                    job_service = JobService(job_repo)
                    page_service = PageService(page_repo)
                    
                    orchestrator = CrawlerOrchestrator(
                        job_id=job_uuid,
                        seed_url=url,
                        job_service=job_service,
                        page_service=page_service
                    )
                    
                    # Concurrently run crawler orchestrator, embedding worker, and categorization worker
                    embed_worker = EmbeddingWorker(job_id=job_id_str, worker_id=f"embed-{job_id_str[:8]}")
                    cat_worker = CategorizationWorker(job_id=job_id_str, worker_id=f"cat-{job_id_str[:8]}")
                    
                    logger.info("Running crawler, embedding, and categorization pipelines concurrently...", job_id=job_id_str)
                    
                    await asyncio.gather(
                        orchestrator.start_crawl(),
                        embed_worker.run(),
                        cat_worker.run(),
                        return_exceptions=True
                    )
                    
                logger.info("Job processing sequence completed", job_id=job_id_str)
            except Exception as e:
                logger.error(f"Error in coordinator daemon loop: {e}", exc_info=True)
                await asyncio.sleep(2)

    asyncio.run(main())
