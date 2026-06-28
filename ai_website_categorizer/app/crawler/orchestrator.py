import asyncio
from uuid import UUID
from typing import List

from app.core.logger import logger, LoggingContext
from app.core.config import get_settings
from app.crawler.frontier import URLFrontier
from app.crawler.robots import RobotsTxtParser
from app.crawler.sitemap import SitemapParser
from app.services.job_service import JobService
from app.models.job import JobStatus
from app.workers.crawler_worker import CrawlerWorker
from app.services.page_service import PageService

class CrawlerOrchestrator:
    def __init__(self, job_id: UUID, seed_url: str, job_service: JobService, page_service: PageService):
        self.job_id = job_id
        self.seed_url = seed_url
        self.job_service = job_service
        self.page_service = page_service
        self.settings = get_settings()
        self.frontier = URLFrontier(str(job_id))
        self.robots_parser = RobotsTxtParser(seed_url)

    async def start_crawl(self):
        with LoggingContext(job_id=str(self.job_id), phase="Orchestrator"):
            try:
                # Update status
                await self.job_service.change_status(self.job_id, JobStatus.RUNNING)
                logger.info(f"Starting crawl job for {self.seed_url}")

                # 1. Fetch robots.txt
                await self.robots_parser.fetch_and_parse()

                # 2. Extract sitemaps and seed frontier
                sitemaps = self.robots_parser.get_sitemaps()
                if not sitemaps:
                    # Try common sitemap locations
                    from urllib.parse import urlparse
                    parsed = urlparse(self.seed_url)
                    sitemaps = [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]

                sitemap_parser = SitemapParser(self.seed_url, self.robots_parser)
                
                sitemap_found = False
                for sitemap_url in sitemaps:
                    try:
                        logger.info(f"Parsing sitemap: {sitemap_url}")
                        async for url in sitemap_parser.fetch_and_parse(sitemap_url):
                            await self.frontier.add_url(url, depth=0, is_sitemap=True)
                            sitemap_found = True
                    except Exception as e:
                        logger.error(f"Error parsing sitemap {sitemap_url}: {e}")

                if not sitemap_found:
                    logger.info("No sitemap found or parsed successfully. Seeding with root URL.")
                    await self.frontier.add_url(self.seed_url, depth=0, is_sitemap=False)

                # 3. Launch worker pool
                from app.renderers import RendererFactory
                renderer_factory = RendererFactory()
                num_workers = self.settings.crawler.max_concurrent_workers
                logger.info(f"Launching {num_workers} concurrent workers")
                
                tasks: List[asyncio.Task] = []
                for _ in range(num_workers):
                    worker = CrawlerWorker(
                        self.job_id,
                        self.seed_url,
                        self.page_service,
                        self.robots_parser,
                        renderer_factory
                    )
                    task = asyncio.create_task(worker.run())
                    tasks.append(task)
                
                # Wait for all workers to finish (frontier depleted)
                await asyncio.gather(*tasks, return_exceptions=True)
                await renderer_factory.close()

                # 4. Finalize Job
                await self.job_service.change_status(self.job_id, JobStatus.COMPLETED)
                logger.info("Crawl job completed successfully.")

            except Exception as e:
                logger.error(f"Fatal error in crawl orchestrator: {e}", exc_info=True)
                await self.job_service.change_status(self.job_id, JobStatus.FAILED)
