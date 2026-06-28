import asyncio
import time
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from app.core.config import get_settings
from app.core.logger import logger, LoggingContext
from app.database.redis_client import redis_client
from app.database.session import get_db_session
from app.models.job import CrawlJob, JobStatus
from app.models.page import Page

class CleanupWorker:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.settings = get_settings()
        # Default retention: 24 hours for completed jobs
        self.retention_hours = 24
        self.run_interval_seconds = 6 * 3600  # run every 6 hours

    async def run(self):
        """Periodic worker loop running cleanup operations."""
        logger.info("Cleanup worker started")
        
        while True:
            # Update heartbeat
            heartbeat_key = f"worker_heartbeat:cleanup:{self.worker_id}"
            await redis_client.set_with_ttl(heartbeat_key, str(time.time()), 90)
            
            try:
                await self._perform_cleanup()
            except Exception as e:
                logger.error(f"Error during periodic cleanup cycle: {e}", exc_info=True)
                
            # Sleep until next interval (check heartbeat in-between)
            sleep_step = 30
            for _ in range(0, self.run_interval_seconds, sleep_step):
                # Update heartbeat every 30 seconds while sleeping
                await redis_client.set_with_ttl(heartbeat_key, str(time.time()), 90)
                await asyncio.sleep(sleep_step)

    async def _perform_cleanup(self):
        with LoggingContext(worker_id=self.worker_id, phase="CleanupCycle"):
            logger.info("Starting periodic database and Redis cleanup cycle...")
            
            cutoff_time = datetime.utcnow() - timedelta(hours=self.retention_hours)
            
            async with get_db_session() as session:
                # 1. Fetch completed or failed jobs older than retention cutoff
                stmt = select(CrawlJob).where(
                    CrawlJob.status.in_([JobStatus.COMPLETED, JobStatus.FAILED]),
                    CrawlJob.completed_at <= cutoff_time
                )
                res = await session.execute(stmt)
                expired_jobs = res.scalars().all()
                
                logger.info(f"Found {len(expired_jobs)} expired jobs older than {self.retention_hours} hours.")
                
                for job in expired_jobs:
                    job_id_str = str(job.id)
                    logger.info(f"Cleaning up Redis assets and boiling templates for job {job_id_str}...")
                    
                    # 2. Clear job-specific Redis keys
                    keys_to_delete = [
                        f"frontier_queue:{job_id_str}",
                        f"frontier_visited:{job_id_str}",
                        f"embedding_queue:{job_id_str}",
                        f"categorization_queue:{job_id_str}",
                        f"retry_queue:{job_id_str}",
                        f"boilerplate_page_count:{job_id_str}",
                        f"rate_limit:{job_id_str}"
                    ]
                    # Delete boilerplate blocks keys
                    # Boilerplate hashes were stored as f"{self.BLOCK_HASH_PREFIX}{job_id}:{block_hash}"
                    # Scan and delete them
                    bp_prefix = f"boilerplate_blocks:{job_id_str}:*"
                    bp_keys = []
                    async for k in redis_client.client.scan_iter(bp_prefix):
                        bp_keys.append(k)
                        
                    all_keys = keys_to_delete + bp_keys
                    if all_keys:
                        await redis_client.client.delete(*all_keys)
                        
                    # 3. Compact / Remove active jobs registration
                    await redis_client.client.srem("active_jobs", job_id_str)
                    
                    # 4. Optional: clear heavy page document page HTML details if present
                    # e.g., if we saved page_document.raw_html, we could set it to None,
                    # but here we keep the structured metadata and just clear Redis footprint.
                    
                logger.info("Cleanup cycle completed successfully.")
