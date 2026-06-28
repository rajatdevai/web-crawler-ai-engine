import time
import hashlib
import dataclasses
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.cleaners.html_cleaner import HTMLCleaner, BoilerplateDetector
from app.cleaners.text_normalizer import TextNormalizer
from app.extractors.html_extractor import HTMLExtractor
from app.extractors.link_extractor import LinkExtractor
from app.extractors.metadata_extractor import MetadataExtractor
from app.renderers.base import RenderResult
from app.repositories.page_repository import PageRepository
from app.models.page import PageStatus
from app.services.page_service import PageService
from app.core.logger import logger, LoggingContext


class ExtractionService:
    def __init__(self, session: AsyncSession, page_service: PageService, seed_url: str):
        self.session = session
        self.page_service = page_service
        self.seed_url = seed_url
        self.page_repo = PageRepository(session)

        self.html_cleaner = HTMLCleaner()
        self.text_normalizer = TextNormalizer()
        self.html_extractor = HTMLExtractor()
        self.link_extractor = LinkExtractor()
        self.metadata_extractor = MetadataExtractor()
        self.boilerplate_detector = BoilerplateDetector()

    async def process(self, page_id: UUID, render_result: RenderResult, job_id: str) -> bool:
        """
        Runs the complete extraction pipeline for a single page.
        Returns True on success, False on failure.
        """
        with LoggingContext(page_id=str(page_id), job_id=job_id, phase="Extraction"):
            page = await self.page_repo.get_by_id(page_id)
            if not page:
                logger.error(f"Page {page_id} not found in DB")
                return False

            await self.page_service.change_status(page_id, PageStatus.EXTRACTING)
            pipeline_start = time.time()
            step_timings = {}

            try:
                # ── Step 1: Clean HTML ──────────────────────────────────────
                t = time.time()
                cleaned_html = self.html_cleaner.clean(render_result.raw_html)
                step_timings["html_clean_ms"] = int((time.time() - t) * 1000)

                # ── Step 2: Extract raw text for normalizing ───────────────
                from bs4 import BeautifulSoup
                raw_text = BeautifulSoup(cleaned_html, "lxml").get_text(separator="\n")

                # ── Step 3: Normalize text ──────────────────────────────────
                t = time.time()
                normalized_text = self.text_normalizer.normalize(raw_text)
                step_timings["text_normalize_ms"] = int((time.time() - t) * 1000)

                # ── Step 4: HTML extraction (structured fields) ────────────
                t = time.time()
                page_content = self.html_extractor.extract(
                    cleaned_html,
                    base_url=render_result.final_url,
                    final_url=render_result.final_url
                )
                # Override body_text with our normalized version
                page_content.body_text = normalized_text
                page_content.word_count = len(normalized_text.split())
                step_timings["html_extract_ms"] = int((time.time() - t) * 1000)

                # ── Step 5: Link extraction ────────────────────────────────
                t = time.time()
                link_result = self.link_extractor.extract(
                    cleaned_html,
                    base_url=render_result.final_url,
                    seed_url=self.seed_url
                )
                step_timings["link_extract_ms"] = int((time.time() - t) * 1000)

                # ── Step 6: Metadata extraction ────────────────────────────
                t = time.time()
                metadata = self.metadata_extractor.extract(cleaned_html)
                step_timings["metadata_extract_ms"] = int((time.time() - t) * 1000)

                # ── Step 7: Boilerplate detection ─────────────────────────
                t = time.time()
                await self.boilerplate_detector.record_page(job_id, normalized_text)
                final_text = await self.boilerplate_detector.remove_boilerplate(job_id, normalized_text)
                page_content.body_text = final_text
                step_timings["boilerplate_ms"] = int((time.time() - t) * 1000)

                # ── Step 8: Content hash ───────────────────────────────────
                content_hash = hashlib.sha256(final_text.encode("utf-8")).hexdigest()

                # ── Step 9: Assemble PageDocument ─────────────────────────
                page_document = {
                    # Core extracted fields
                    "title": page_content.title,
                    "canonical_url": page_content.canonical_url,
                    "meta_description": page_content.meta_description,
                    "page_language": page_content.page_language,
                    "word_count": page_content.word_count,
                    "body_text": page_content.body_text,
                    # Headers
                    "h1_tags": page_content.h1_tags,
                    "h2_tags": page_content.h2_tags,
                    "h3_tags": page_content.h3_tags,
                    # Structured
                    "breadcrumbs": page_content.breadcrumbs,
                    "structured_data": page_content.structured_data,
                    "og_data": page_content.og_data,
                    "twitter_data": page_content.twitter_data,
                    # Links
                    "internal_links": [lk.href for lk in link_result.internal_links],
                    "external_links": [lk.href for lk in link_result.external_links],
                    "pagination_links": [lk.href for lk in link_result.pagination_links],
                    "download_links": [lk.href for lk in link_result.download_links],
                    # Supplementary
                    "image_alts": page_content.image_alts,
                    "form_fields": page_content.form_fields,
                    "table_text": page_content.table_text,
                    # Schema.org metadata
                    "metadata": {
                        "products": metadata.products,
                        "services": metadata.services,
                        "faqs": metadata.faqs,
                        "articles": metadata.articles,
                        "reviews": metadata.reviews,
                        "organizations": metadata.organizations,
                        "offers": metadata.offers,
                    },
                    # Render context
                    "render_method": render_result.render_method.value,
                    "render_duration_ms": render_result.render_duration_ms,
                    "detected_technologies": render_result.detected_technologies,
                    # Pipeline metrics
                    "pipeline_timings_ms": step_timings,
                    "total_pipeline_ms": int((time.time() - pipeline_start) * 1000),
                }

                # ── Step 10: Persist to DB ─────────────────────────────────
                # Storage tier contract:
                #   page_document (JSONB) -> PostgreSQL: canonical source of truth for all AI services
                #   content_hash          -> PostgreSQL: deduplication index
                #   embedding_queue       -> Redis:      transient job signal only (NOT persistent storage)
                #   Raw HTML / screenshots -> S3:        if archival is ever needed (not implemented here)
                from sqlalchemy import update
                from app.models.page import Page
                stmt = (
                    update(Page)
                    .where(Page.id == page_id)
                    .values(
                        page_document=page_document,   # canonical JSONB — source of truth
                        content_hash=content_hash,
                        canonical_url=page_content.canonical_url,
                        extracted_at=datetime.utcnow(),
                    )
                )
                await self.session.execute(stmt)
                await self.session.commit()

                # ── Step 11: Transition state ──────────────────────────────
                await self.page_service.change_status(page_id, PageStatus.EXTRACTED)
                await self.session.commit()

                logger.info(
                    "Extraction complete",
                    word_count=page_content.word_count,
                    content_hash=content_hash[:8],
                    timings=step_timings
                )

                # ── Step 12: Signal embedding worker via Redis queue ────────
                # IMPORTANT: Redis is used ONLY as a transient job signal queue.
                # The actual PageDocument lives in PostgreSQL (page_document column).
                # The embedding worker reads page_document from DB using this page_id pointer.
                from app.database.redis_client import redis_client
                import json
                await redis_client.push_to_queue(
                    f"embedding_queue:{job_id}",
                    json.dumps({"page_id": str(page_id), "job_id": job_id})
                )

                return True

            except Exception as e:
                logger.error(f"Extraction pipeline failed at step: {e}", exc_info=True)
                await self.page_service.change_status(
                    page_id, PageStatus.FAILED,
                    {"error": str(e), "phase": "extraction", "timings": step_timings}
                )
                await self.session.commit()
                return False
