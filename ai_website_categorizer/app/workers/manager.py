import asyncio
import json
import signal
import sys
import time
from uuid import UUID
from typing import Dict, List, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.logger import logger, LoggingContext
from app.database.redis_client import redis_client
from app.database.session import get_db_session
from app.models.job import CrawlJob, JobStatus
from app.models.page import Page, PageStatus

# Import worker classes
from app.workers.crawler_worker import CrawlerWorker
from app.workers.embedding_worker import EmbeddingWorker
from app.workers.categorization_worker import CategorizationWorker
from app.workers.retry_worker import RetryWorker
from app.workers.cleanup_worker import CleanupWorker
from app.crawler.orchestrator import CrawlerOrchestrator
from app.services.job_service import JobService
from app.services.page_service import PageService
from app.services.category_service import CategoryService
from app.repositories.job_repository import JobRepository
from app.repositories.page_repository import PageRepository

# Global shutdown event
shutdown_event = asyncio.Event()


class WorkerManager:
    def __init__(self):
        self.settings = get_settings()
        self.tasks: Dict[str, asyncio.Task] = {}
        self.worker_id = f"manager-{int(time.time())}"

    async def start(self):
        logger.info("Starting Worker Manager daemon...", manager_id=self.worker_id)
        
        # Setup OS signal handlers for graceful shutdown
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
                except NotImplementedError:
                    pass

        # Register active tasks
        self.tasks["orchestrator"] = asyncio.create_task(self._run_global_orchestrator())
        
        # Crawler pool
        num_crawlers = self.settings.crawler.max_concurrent_workers
        for i in range(num_crawlers):
            self.tasks[f"crawler_{i}"] = asyncio.create_task(self._run_global_crawler(f"crawler_{i}"))
            
        self.tasks["embedding"] = asyncio.create_task(self._run_global_embedding())
        self.tasks["categorizer"] = asyncio.create_task(self._run_global_categorizer())
        self.tasks["retry"] = asyncio.create_task(self._run_global_retry())
        self.tasks["cleanup"] = asyncio.create_task(CleanupWorker(self.worker_id).run())

        # Start supervisor loop
        await self._supervisor_loop()

    async def _supervisor_loop(self):
        """Supervises and heals crashed tasks. Checks heartbeats."""
        logger.info("Worker Manager supervisor active.")
        
        while not shutdown_event.is_set():
            # Update manager heartbeat
            await redis_client.set_with_ttl(f"worker_heartbeat:manager:{self.worker_id}", str(time.time()), 90)
            
            # Audit all active worker tasks
            for name, task in list(self.tasks.items()):
                if task.done():
                    exc = task.exception()
                    if exc:
                        logger.error(f"Task '{name}' crashed with error: {exc}. Restarting in 5s...", exc_info=exc)
                    else:
                        logger.warning(f"Task '{name}' finished unexpectedly. Restarting in 5s...")
                    
                    await asyncio.sleep(5)
                    self._restart_task(name)

                # Check Redis heartbeat freshness
                heartbeat_key = f"worker_heartbeat:{name.split('_')[0]}:{self.worker_id}"
                if name.startswith("crawler_"):
                    heartbeat_key = f"worker_heartbeat:crawler:{name}"
                    
                hb_val = await redis_client.get(heartbeat_key)
                if hb_val:
                    elapsed = time.time() - float(hb_val)
                    if elapsed > 60:
                        logger.warning(f"Worker heartbeat stale for {name} ({elapsed:.1f}s). Restarting task.")
                        task.cancel()
                        self._restart_task(name)

            await asyncio.sleep(10)

    def _restart_task(self, name: str):
        """Restarts a specific task by name."""
        if name == "orchestrator":
            self.tasks[name] = asyncio.create_task(self._run_global_orchestrator())
        elif name.startswith("crawler_"):
            self.tasks[name] = asyncio.create_task(self._run_global_crawler(name))
        elif name == "embedding":
            self.tasks[name] = asyncio.create_task(self._run_global_embedding())
        elif name == "categorizer":
            self.tasks[name] = asyncio.create_task(self._run_global_categorizer())
        elif name == "retry":
            self.tasks[name] = asyncio.create_task(self._run_global_retry())
        elif name == "cleanup":
            self.tasks[name] = asyncio.create_task(CleanupWorker(self.worker_id).run())

    async def shutdown(self):
        """Gracefully drains in-flight work before exiting."""
        logger.info("Shutdown signal received. Initiating graceful shutdown sequence...")
        shutdown_event.set()

        # Wait for active FETCHING/EXTRACTING pages to complete
        logger.info("Draining in-flight database actions...")
        drain_timeout = 30
        start_drain = time.time()
        
        while time.time() - start_drain < drain_timeout:
            async with get_db_session() as session:
                # Count in-flight pages
                stmt = select(func.count(Page.id)).where(
                    Page.status.in_([PageStatus.FETCHING, PageStatus.EXTRACTING])
                )
                res = await session.execute(stmt)
                in_flight_count = res.scalar() or 0
                
                if in_flight_count == 0:
                    logger.info("All in-flight pages processed successfully.")
                    break
                
                logger.info(f"Waiting for {in_flight_count} in-flight pages to complete...")
                await asyncio.sleep(2)
        else:
            logger.warning("Graceful drain timed out. Terminating remaining tasks.")

        # Cancel all running tasks
        for name, task in self.tasks.items():
            task.cancel()
            
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        logger.info("Shutdown completed. Worker process exiting.")
        sys.exit(0)

    # ─────────────────────────────────────────────────────────────────────────
    # Global Task Loops
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_global_orchestrator(self):
        """Polls job_start_queue and initializes jobs."""
        logger.info("Orchestrator task active.")
        hb_key = f"worker_heartbeat:orchestrator:{self.worker_id}"
        
        while not shutdown_event.is_set():
            await redis_client.set_with_ttl(hb_key, str(time.time()), 90)
            
            raw = await redis_client.pop_from_queue("job_start_queue", timeout=2)
            if not raw:
                continue

            try:
                event = json.loads(raw)
                job_id_str = event["job_id"]
                url = event["url"]
                job_uuid = UUID(job_id_str)
                
                logger.info(f"Orchestrator received start request for job {job_id_str}")
                await redis_client.add_job_event(job_id_str, "🤖 Initializing crawl job...")
                
                # Fetch sitemaps and seed URL Frontier
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
                    
                    # Run the seeding logic (robots.txt, sitemaps, seed root)
                    await redis_client.add_job_event(job_id_str, "🔍 Inspecting site rules (robots.txt) and sitemaps...")
                    await orchestrator.robots_parser.fetch_and_parse()
                    sitemaps = orchestrator.robots_parser.get_sitemaps()
                    if not sitemaps:
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        sitemaps = [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
                        
                    from app.crawler.sitemap import SitemapParser
                    sitemap_parser = SitemapParser(url, orchestrator.robots_parser)
                    
                    allowed_prefix = event.get("config", {}).get("allowed_path_prefix") if event else None
                    if allowed_prefix:
                        await redis_client.add_job_event(job_id_str, f"⚙️ Applying section filter: only URLs matching prefix '{allowed_prefix}' will be scheduled.")
                    
                    sitemap_found = False
                    for sitemap_url in sitemaps:
                        try:
                            sitemap_logged = False
                            async for sm_url in sitemap_parser.fetch_and_parse(sitemap_url):
                                if allowed_prefix:
                                    from urllib.parse import urlparse as parse_url
                                    if not parse_url(sm_url).path.startswith(allowed_prefix):
                                        continue
                                if not sitemap_logged:
                                    await redis_client.add_job_event(job_id_str, f"📍 Seeding crawl frontier from sitemap: {sitemap_url}")
                                    sitemap_logged = True
                                await orchestrator.frontier.add_url(sm_url, depth=0, is_sitemap=True)
                                sitemap_found = True
                        except Exception as e:
                            logger.error(f"Sitemap parsing failed for {sitemap_url}: {e}")
                            
                    if not sitemap_found:
                        await redis_client.add_job_event(job_id_str, f"🌱 Seeding crawl frontier with root URL: {url}")
                        await orchestrator.frontier.add_url(url, depth=0)
                    else:
                        await redis_client.add_job_event(job_id_str, f"🌱 Seeded frontier from sitemaps successfully.")
                        
                    # Transition job to RUNNING
                    await job_service.change_status(job_uuid, JobStatus.RUNNING)
                    await session.commit()
                    
                # Add to active_jobs set
                await redis_client.client.sadd("active_jobs", job_id_str)
                await redis_client.add_job_event(job_id_str, "🚀 Crawl process started and workers activated.")
                logger.info(f"Job {job_id_str} registered as active and seeded.")
            except Exception as e:
                logger.error(f"Error in orchestrator loop: {e}", exc_info=True)

    async def _run_global_crawler(self, crawler_name: str):
        """Crawler loop polling frontiers for all active jobs."""
        logger.info(f"Crawler task {crawler_name} active.")
        hb_key = f"worker_heartbeat:crawler:{crawler_name}"
        
        from app.renderers import RendererFactory
        renderer_factory = RendererFactory()
        
        try:
            while not shutdown_event.is_set():
                await redis_client.set_with_ttl(hb_key, str(time.time()), 90)
                
                active_jobs = await redis_client.client.smembers("active_jobs")
                if not active_jobs:
                    await asyncio.sleep(2)
                    continue

                processed_any = False
                for job_id_str in active_jobs:
                    job_uuid = UUID(job_id_str)
                    
                    async with get_db_session() as session:
                        page_repo = PageRepository(session)
                        page_service = PageService(page_repo)
                        
                        # We need RobotsTxtParser for rules validation
                        # Keep cached instance per job if possible, or build simple mock
                        from app.crawler.robots import RobotsTxtParser
                        # Retrieve seed URL for this job to instantiate parser
                        job_repo = JobRepository(session)
                        job = await job_repo.get_by_id(job_uuid)
                        if not job:
                            await redis_client.client.srem("active_jobs", job_id_str)
                            continue
                            
                        robots_parser = RobotsTxtParser(job.url)
                        # Fetch is cached in Redis so this is fast
                        await robots_parser.fetch_and_parse()
                        
                        worker = CrawlerWorker(
                            job_id=job_uuid,
                            seed_url=job.url,
                            page_service=page_service,
                            robots_parser=robots_parser,
                            renderer_factory=renderer_factory,
                            allowed_path_prefix=job.config.get("allowed_path_prefix") if job.config else None
                        )
                        
                        # Process one URL from this job's frontier
                        max_pages_limit = job.config.get("max_pages") or self.settings.crawler.max_pages
                        stmt_count = select(func.count(Page.id)).where(Page.job_id == job_uuid)
                        res_count = await session.execute(stmt_count)
                        current_count = res_count.scalar() or 0
                        
                        if current_count >= max_pages_limit:
                            logger.info(f"Job {job_id_str} reached max_pages limit of {max_pages_limit}. Draining frontier.")
                            await redis_client.client.delete(worker.frontier.queue_key)
                            item = None
                        else:
                            item = await worker.frontier.get_next_url()

                        if item:
                            processed_any = True
                            await worker._process_url(item["url"], item["depth"], item["parent_url"])
                            
                        # If frontier is empty and no in-flight items exist in database
                        # we can transition job to COMPLETED and unregister active_jobs.
                        else:
                            # Verify if job is actually RUNNING in the DB
                            if job.status == JobStatus.RUNNING:
                                # Verify if any pages are still in-flight
                                stmt_inflight = select(func.count(Page.id)).where(
                                    Page.job_id == job_uuid,
                                    Page.status.in_([PageStatus.FETCHING, PageStatus.EXTRACTING, PageStatus.CLASSIFYING])
                                )
                                res_inflight = await session.execute(stmt_inflight)
                                inflight = res_inflight.scalar() or 0
                                
                                # Also check queues
                                queue_size = await worker.frontier.get_queue_size()
                                emb_queue = await redis_client.get_list_length(f"embedding_queue:{job_id_str}") or 0
                                cat_queue = await redis_client.get_list_length(f"categorization_queue:{job_id_str}") or 0
                                
                                if inflight == 0 and queue_size == 0 and emb_queue == 0 and cat_queue == 0:
                                    logger.info(f"All items completed for job {job_id_str}. Finalizing job status.")
                                    await redis_client.add_job_event(job_id_str, "🎉 Crawl job finished successfully! All pages are categorized.")
                                    await redis_client.client.srem("active_jobs", job_id_str)
                                    await JobService(job_repo).change_status(job_uuid, JobStatus.COMPLETED)
                                    await session.commit()
                                
                if not processed_any:
                    await asyncio.sleep(2)
        finally:
            await renderer_factory.close()

    async def _run_global_embedding(self):
        """Embedding loop polling embedding queues for all active jobs."""
        logger.info("Embedding task active.")
        hb_key = f"worker_heartbeat:embedding:{self.worker_id}"
        
        while not shutdown_event.is_set():
            await redis_client.set_with_ttl(hb_key, str(time.time()), 90)
            
            active_jobs = await redis_client.client.smembers("active_jobs")
            if not active_jobs:
                await asyncio.sleep(2)
                continue
                
            processed_any = False
            for job_id_str in active_jobs:
                emb_worker = EmbeddingWorker(job_id=job_id_str, worker_id=self.worker_id)
                # Accumulate and process a single batch
                batch_items = await emb_worker._accumulate_batch()
                if batch_items:
                    processed_any = True
                    async with get_db_session() as session:
                        from app.embeddings.generator import EmbeddingGenerator
                        generator = EmbeddingGenerator(session=session, job_id=job_id_str)
                        await emb_worker._process_batch(batch_items, generator, session)
                        
            if not processed_any:
                await asyncio.sleep(2)

    async def _run_global_categorizer(self):
        """Categorization loop polling categorization queues for all active jobs."""
        logger.info("Categorizer task active.")
        hb_key = f"worker_heartbeat:categorizer:{self.worker_id}"
        
        while not shutdown_event.is_set():
            await redis_client.set_with_ttl(hb_key, str(time.time()), 90)
            
            active_jobs = await redis_client.client.smembers("active_jobs")
            if not active_jobs:
                await asyncio.sleep(2)
                continue
                
            processed_any = False
            for job_id_str in active_jobs:
                # Read single item
                raw = await redis_client.pop_from_queue(f"categorization_queue:{job_id_str}", timeout=1)
                if raw:
                    processed_any = True
                    item = json.loads(raw)
                    async with get_db_session() as session:
                        cat_service = CategoryService(session)
                        await cat_service.load_centroids_from_db()
                        
                        cat_worker = CategorizationWorker(job_id=job_id_str, worker_id=self.worker_id)
                        await cat_worker._process_page(
                            page_id=UUID(item["page_id"]),
                            job_id=UUID(item["job_id"]),
                            session=session,
                            category_service=cat_service,
                        )
            if not processed_any:
                await asyncio.sleep(2)

    async def _run_global_retry(self):
        """Retry loop polling retry queues for all active jobs."""
        logger.info("Retry task active.")
        hb_key = f"worker_heartbeat:retry:{self.worker_id}"
        
        while not shutdown_event.is_set():
            await redis_client.set_with_ttl(hb_key, str(time.time()), 90)
            
            active_jobs = await redis_client.client.smembers("active_jobs")
            if not active_jobs:
                await asyncio.sleep(2)
                continue
                
            processed_any = False
            for job_id_str in active_jobs:
                raw = await redis_client.pop_from_queue(f"retry_queue:{job_id_str}", timeout=1)
                if raw:
                    processed_any = True
                    item = json.loads(raw)
                    retry_worker = RetryWorker(job_id=job_id_str, worker_id=self.worker_id)
                    await retry_worker._process_retry(item)
                    
            if not processed_any:
                await asyncio.sleep(2)


if __name__ == "__main__":
    manager = WorkerManager()
    asyncio.run(manager.start())
