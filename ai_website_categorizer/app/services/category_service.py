"""
Category Service — Centroid Lifecycle Manager

Maintains per-category embedding centroids.
Automatically recomputes centroid every time a category accumulates 10 new classified pages.

Design:
  - Centroids live in memory (fast) AND are persisted to the `categories` table as JSONB.
  - On worker startup, centroids are loaded from DB so no warm-up loss on restarts.
  - centroid_counts tracks how many pages contributed to each centroid.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional
from uuid import UUID

import numpy as np
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.embeddings.generator import SimilarityEngine
from app.models.category import Category
from app.models.embedding import PageEmbedding
from app.models.page import Page

RECOMPUTE_EVERY_N = 10  # recompute centroid after every 10 new pages


class CategoryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        # In-memory state
        self._centroids: Dict[str, np.ndarray] = {}          # category_name -> centroid
        self._centroid_counts: Dict[str, int] = {}           # category_name -> page count
        self._pending_counts: Dict[str, int] = {}            # pages since last recompute

    @property
    def centroids(self) -> Dict[str, np.ndarray]:
        return self._centroids

    @property
    def centroid_counts(self) -> Dict[str, int]:
        return self._centroid_counts

    async def load_centroids_from_db(self) -> None:
        """Load persisted centroids from DB on worker startup."""
        stmt = select(Category).where(Category.centroid.isnot(None))
        result = await self.session.execute(stmt)
        categories = result.scalars().all()
        for cat in categories:
            if cat.centroid:
                self._centroids[cat.name] = np.array(cat.centroid, dtype=np.float32)
                self._centroid_counts[cat.name] = cat.page_count or 0
        logger.info(f"Loaded {len(self._centroids)} category centroids from DB.")

    async def record_classification(
        self,
        category_name: str,
        page_id: UUID,
        job_id: UUID,
    ) -> None:
        """
        Records a new page classified into a category.
        Triggers centroid recomputation every RECOMPUTE_EVERY_N pages.
        """
        self._pending_counts[category_name] = self._pending_counts.get(category_name, 0) + 1
        self._centroid_counts[category_name] = self._centroid_counts.get(category_name, 0) + 1

        if self._pending_counts[category_name] >= RECOMPUTE_EVERY_N:
            await self._recompute_centroid(category_name, job_id)
            self._pending_counts[category_name] = 0

    async def _recompute_centroid(self, category_name: str, job_id: UUID) -> None:
        """
        Fetches all embeddings for pages classified into this category within this job.
        Recomputes and persists the centroid.
        """
        stmt = (
            select(PageEmbedding.vector)
            .join(Page, PageEmbedding.page_id == Page.id)
            .where(Page.job_id == job_id)
            .where(
                # JSON path query: classification_result->>'final_category' = category_name
                Page.classification_result["final_category"].astext == category_name
            )
        )
        result = await self.session.execute(stmt)
        vectors_raw = result.scalars().all()

        if not vectors_raw:
            logger.warning(f"No embeddings found for category '{category_name}', skipping centroid update.")
            return

        vectors = [np.array(v, dtype=np.float32) for v in vectors_raw]
        new_centroid = SimilarityEngine.compute_centroid(vectors)
        self._centroids[category_name] = new_centroid
        self._centroid_counts[category_name] = len(vectors)

        # Persist to DB
        stmt_update = (
            update(Category)
            .where(Category.name == category_name)
            .values(
                centroid=new_centroid.tolist(),
                page_count=len(vectors),
            )
        )
        await self.session.execute(stmt_update)
        await self.session.commit()

        logger.info(
            "Centroid recomputed",
            category=category_name,
            pages_used=len(vectors),
        )

    async def get_or_create_category(self, name: str, job_id: Optional[Any] = None) -> Category:
        """Returns existing category or creates a new one."""
        stmt = select(Category).where(Category.name == name)
        if job_id:
            stmt = stmt.where(Category.job_id == job_id)
        result = await self.session.execute(stmt)
        cat = result.scalars().first()
        if not cat:
            cat = Category(name=name, job_id=job_id)
            self.session.add(cat)
            await self.session.commit()
            await self.session.refresh(cat)
        return cat
