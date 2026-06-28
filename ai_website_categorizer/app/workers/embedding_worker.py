"""
Embedding Worker

Consumes page_ids from `embedding_queue:{job_id}` in Redis.

Batching strategy:
  - Accumulate up to EMBEDDING_BATCH_SIZE items OR wait up to 5 seconds,
    whichever comes first. This prevents API under-utilisation on slow crawls
    while keeping latency bounded on fast crawls.

Storage contract (enforced here):
  - Reads page_document from PostgreSQL (source of truth).
  - Writes vectors to page_embeddings table (PostgreSQL).
  - Pushes page_id pointer to categorization_queue in Redis (transient signal only).
  - Never writes embedding vectors to Redis.
"""
import asyncio
import json
import time
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import logger, LoggingContext
from app.database.redis_client import redis_client
from app.database.session import get_db_session
from app.embeddings.generator import EmbeddingGenerator, BudgetExceededException
from app.embeddings.input_builder import build_embedding_input
from app.models.page import Page, PageStatus
from app.observability.metrics import worker_active_gauge


CATEGORIZATION_QUEUE_PREFIX = "categorization_queue:"
EMBEDDING_QUEUE_PREFIX = "embedding_queue:"
BATCH_WAIT_SECONDS = 5.0


class EmbeddingWorker:
    def __init__(self, job_id: str, worker_id: str):
        self.job_id = job_id
        self.worker_id = worker_id
        self.settings = get_settings()
        self.queue_key = f"{EMBEDDING_QUEUE_PREFIX}{job_id}"
        self.cat_queue_key = f"{CATEGORIZATION_QUEUE_PREFIX}{job_id}"
        self.batch_size = self.settings.embedding.batch_size

        # Worker metrics
        self._batches_processed = 0
        self._pages_embedded = 0
        self._total_api_latency_ms = 0

    async def run(self) -> None:
        """Main worker loop. Runs until the queue is empty and no items arrive."""
        worker_active_gauge.labels(worker_id=self.worker_id).set(1)
        self._budget_exceeded = False

        with LoggingContext(job_id=self.job_id, worker_id=self.worker_id, phase="EmbeddingWorker"):
            logger.info("Embedding worker started")

            # get_db_session() is an async context manager (not a generator).
            # Using get_async_session() (a generator) with "async with" would TypeError at runtime.
            async with get_db_session() as session:
                generator = EmbeddingGenerator(session=session, job_id=self.job_id)
                idle_rounds = 0

                while not self._budget_exceeded:
                    batch_items = await self._accumulate_batch()

                    if not batch_items:
                        idle_rounds += 1
                        if idle_rounds >= 3:
                            logger.info("Embedding queue empty for 3 consecutive rounds. Worker exiting.")
                            break
                        continue

                    idle_rounds = 0
                    await self._process_batch(batch_items, generator, session)

        worker_active_gauge.labels(worker_id=self.worker_id).set(0)
        logger.info(
            "Embedding worker finished",
            batches_processed=self._batches_processed,
            pages_embedded=self._pages_embedded,
            budget_exceeded=getattr(self, "_budget_exceeded", False),
        )

    async def _accumulate_batch(self) -> List[Dict]:
        """
        Accumulates up to batch_size items from the queue.
        Waits at most BATCH_WAIT_SECONDS before processing whatever it has.
        """
        batch: List[Dict] = []
        deadline = time.monotonic() + BATCH_WAIT_SECONDS

        while len(batch) < self.batch_size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            # Non-blocking pop attempt (timeout=1s to stay responsive)
            raw = await redis_client.pop_from_queue(self.queue_key, timeout=min(1, int(remaining) + 1))
            if raw:
                try:
                    batch.append(json.loads(raw))
                except json.JSONDecodeError:
                    logger.warning(f"Malformed queue item skipped: {raw}")

        return batch

    async def _process_batch(
        self,
        batch_items: List[Dict],
        generator: EmbeddingGenerator,
        session: AsyncSession,
    ) -> None:
        """Fetches page_documents from DB, builds inputs, generates embeddings, enqueues."""
        page_ids: List[UUID] = []
        texts: List[str] = []

        for item in batch_items:
            try:
                page_id = UUID(item["page_id"])
                # Read page_document from PostgreSQL — Redis holds ONLY the pointer
                stmt = select(Page).where(Page.id == page_id)
                result = await session.execute(stmt)
                page = result.scalars().first()

                if not page or not page.page_document:
                    logger.warning(f"Page {page_id} has no page_document, skipping.")
                    continue

                embedding_input = build_embedding_input(page.page_document)
                if not embedding_input.strip():
                    logger.warning(f"Empty embedding input for page {page_id}, skipping.")
                    continue

                page_ids.append(page_id)
                texts.append(embedding_input)

            except Exception as e:
                logger.error(f"Failed to prepare embedding input for {item}: {e}")

        if not page_ids:
            return

        await redis_client.add_job_event(self.job_id, f"⚡ Generating semantic text embeddings for {len(page_ids)} pages...")
        t_start = time.time()
        try:
            await generator.embed_batch(page_ids=page_ids, texts=texts)
            elapsed_ms = int((time.time() - t_start) * 1000)

            self._batches_processed += 1
            self._pages_embedded += len(page_ids)
            self._total_api_latency_ms += elapsed_ms

            avg_latency = self._total_api_latency_ms / self._batches_processed
            pages_per_sec = self._pages_embedded / max(1, self._total_api_latency_ms / 1000)

            logger.info(
                "Batch embedded",
                batch_size=len(page_ids),
                elapsed_ms=elapsed_ms,
                pages_per_second=round(pages_per_sec, 2),
                avg_api_latency_ms=round(avg_latency, 1),
            )

            # Push page_id pointers to categorization queue (Redis — transient signal only)
            for page_id in page_ids:
                await redis_client.push_to_queue(
                    self.cat_queue_key,
                    json.dumps({"page_id": str(page_id), "job_id": self.job_id}),
                )

        except BudgetExceededException as e:
            logger.error(f"BUDGET EXCEEDED: {e}. Stopping embedding worker cleanly.")
            # Set flag so the outer while-loop exits gracefully after this batch.
            self._budget_exceeded = True
            
            # Transition CrawlJob state to FAILED and persist error summary
            from app.repositories.job_repository import JobRepository
            from app.services.job_service import JobService
            from app.models.job import JobStatus
            try:
                job_uuid = UUID(self.job_id)
                job_repo = JobRepository(session)
                job_service = JobService(job_repo)
                await job_service.change_status(job_uuid, JobStatus.FAILED)
                
                # Fetch and add error summary details
                job = await job_repo.get_by_id(job_uuid)
                if job:
                    job.error_summary = {
                        "error_code": "BUDGET_EXCEEDED",
                        "message": str(e),
                        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z"
                    }
                    await session.commit()
            except Exception as db_err:
                logger.error(f"Failed to record job failure for budget limit: {db_err}")

        except Exception as e:
            logger.error(f"Embedding batch failed: {e}", exc_info=True)
            # Individual page failures must not kill the whole batch worker.
