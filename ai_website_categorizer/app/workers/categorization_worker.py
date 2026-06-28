"""
Categorization Worker

Consumes page_ids from `categorization_queue:{job_id}`.
Drives the three-stage classification cascade for each page.

Flow per page:
  1. Load page_document from PostgreSQL
  2. Load embedding vector from page_embeddings table
  3. Stage 1: DeterministicClassifier (zero API)
  4. Stage 2: EmbeddingClassifier if Stage 1 insufficient (zero API)
  5. Stage 3: LLMClassifier if Stage 2 insufficient (API call)
  6. ConfidenceEngine assembles final ClassificationResult
  7. Persist classification_result JSONB + category_id to pages table
  8. Update CategoryService centroid lifecycle
  9. Emit metrics
"""
import asyncio
import json
import time
from typing import Optional
from uuid import UUID

import numpy as np
from sqlalchemy import select, update

from app.categorizer.confidence import ConfidenceEngine
from app.categorizer.deterministic import DeterministicClassifier
from app.categorizer.embedding_classifier import EmbeddingClassifier
from app.categorizer.llm_classifier import LLMClassifier, UNCATEGORIZED
from app.core.config import get_settings
from app.core.logger import logger, LoggingContext
from app.database.redis_client import redis_client
from app.database.session import get_db_session
from app.models.embedding import PageEmbedding
from app.models.page import Page, PageStatus
from app.observability.metrics import (
    pages_classified_total,
    worker_active_gauge,
    llm_calls_total,
)
from app.services.category_service import CategoryService

CATEGORIZATION_QUEUE_PREFIX = "categorization_queue:"
BATCH_WAIT_SECONDS = 5.0


class CategorizationWorker:
    def __init__(self, job_id: str, worker_id: str):
        self.job_id = job_id
        self.worker_id = worker_id
        self.settings = get_settings()
        self.queue_key = f"{CATEGORIZATION_QUEUE_PREFIX}{job_id}"

        self._deterministic = DeterministicClassifier(
            signal_dict=getattr(self.settings.classification, "signal_dict", None)
        )
        self._llm = LLMClassifier()
        self._confidence_engine = ConfidenceEngine()

        # Metrics
        self._classified_count = {"deterministic": 0, "embedding": 0, "llm": 0, "none": 0}

    async def run(self) -> None:
        worker_active_gauge.labels(worker_id=self.worker_id).set(1)

        with LoggingContext(job_id=self.job_id, worker_id=self.worker_id, phase="CategorizationWorker"):
            logger.info("Categorization worker started")

            async with get_db_session() as session:
                category_service = CategoryService(session)
                await category_service.load_centroids_from_db()

                idle_rounds = 0
                while True:
                    raw = await redis_client.pop_from_queue(self.queue_key, timeout=5)
                    if not raw:
                        idle_rounds += 1
                        if idle_rounds >= 3:
                            logger.info("Categorization queue empty for 3 rounds. Worker exiting.")
                            break
                        continue

                    idle_rounds = 0
                    try:
                        item = json.loads(raw)
                        await self._process_page(
                            page_id=UUID(item["page_id"]),
                            job_id=UUID(item["job_id"]),
                            session=session,
                            category_service=category_service,
                        )
                    except Exception as e:
                        logger.error(f"Error processing categorization item {raw}: {e}", exc_info=True)

        worker_active_gauge.labels(worker_id=self.worker_id).set(0)
        logger.info("Categorization worker finished", method_breakdown=self._classified_count)

    async def _process_page(
        self,
        page_id: UUID,
        job_id: UUID,
        session,
        category_service: CategoryService,
    ) -> None:
        """Full 3-stage classification cascade for one page."""
        t_start = time.monotonic()
        with LoggingContext(page_id=str(page_id), phase="Classify"):
            # ── Load page_document from PostgreSQL ───────────────────────
            stmt = select(Page).where(Page.id == page_id)
            result = await session.execute(stmt)
            page = result.scalars().first()

            if not page or not page.page_document:
                logger.warning(f"Page {page_id} missing page_document. Skipping.")
                return

            doc = page.page_document

            # ── Load embedding vector ────────────────────────────────────
            emb_stmt = select(PageEmbedding).where(PageEmbedding.page_id == page_id)
            emb_result = await session.execute(emb_stmt)
            emb_row = emb_result.scalars().first()
            page_vector: Optional[np.ndarray] = (
                np.array(emb_row.vector, dtype=np.float32) if emb_row else None
            )

            # ── Stage 1: Deterministic ───────────────────────────────────
            det_result = self._deterministic.classify(doc, page_url=page.url)

            if det_result.skipped:
                logger.debug(f"Page {page_id} is a utility page, skipping classification.")
                return

            if det_result.matched_category:
                # Stage 1 sufficient
                final = self._confidence_engine.assemble(deterministic=det_result)
                self._classified_count["deterministic"] += 1
            else:
                # ── Stage 2: Embedding Classifier ────────────────────────
                emb_classifier = EmbeddingClassifier(
                    centroids=category_service.centroids,
                    centroid_counts=category_service.centroid_counts,
                )

                emb_result_obj = None
                if page_vector is not None:
                    emb_result_obj = emb_classifier.classify(
                        page_embedding=page_vector,
                        page_id=str(page_id),
                    )

                if emb_result_obj and emb_result_obj.matched_category:
                    # Stage 2 sufficient
                    final = self._confidence_engine.assemble(
                        deterministic=det_result,
                        embedding=emb_result_obj,
                    )
                    self._classified_count["embedding"] += 1
                else:
                    # ── Stage 3: LLM Classifier ──────────────────────────
                    await redis_client.add_job_event(str(job_id), f"🧠 Asking AI to classify page: {page.url}")
                    llm_result = await self._llm.classify(doc)
                    final = self._confidence_engine.assemble(
                        deterministic=det_result,
                        embedding=emb_result_obj,
                        llm=llm_result,
                    )
                    self._classified_count["llm"] += 1
                    llm_calls_total.labels(job_id=str(job_id)).inc()

            # ── Persist ClassificationResult ─────────────────────────────
            # Get or create the Category row for the FK
            category_row = None
            if final.final_category != UNCATEGORIZED:
                category_row = await category_service.get_or_create_category(
                    final.final_category, 
                    job_id=UUID(self.job_id)
                )

            duration_ms = int((time.monotonic() - t_start) * 1000)
            res_dict = final.to_dict()
            res_dict["classification_duration_ms"] = duration_ms

            stmt_update = (
                update(Page)
                .where(Page.id == page_id)
                .values(
                    classification_result=res_dict,
                    category_id=category_row.id if category_row else None,
                    status=PageStatus.CLASSIFIED,
                    classified_at=__import__("datetime").datetime.utcnow(),
                )
            )
            await session.execute(stmt_update)
            await session.commit()

            # ── Update centroid lifecycle ────────────────────────────────
            if final.final_category != UNCATEGORIZED and category_row:
                await category_service.record_classification(
                    category_name=final.final_category,
                    page_id=page_id,
                    job_id=job_id,
                )

            pages_classified_total.labels(
                job_id=str(job_id),
                method=final.classification_method,
                category=final.final_category,
            ).inc()

            logger.info(
                "Page classified",
                category=final.final_category,
                method=final.classification_method,
                confidence=round(final.final_confidence, 3),
                needs_human_review=final.needs_human_review,
            )
            confidence_pct = int(final.final_confidence * 100)
            await redis_client.add_job_event(
                str(job_id),
                f"✅ Classified '{page.url}' → {final.final_category} ({confidence_pct}% confidence, via {final.classification_method})"
            )
