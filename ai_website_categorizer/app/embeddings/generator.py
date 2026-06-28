"""
Embedding Generator

Provides:
  - EmbeddingGenerator: OpenAI + SentenceTransformers providers, batching, budget tracking.
  - SimilarityEngine:   cosine similarity, centroid, KMeans clustering.

Storage contract:
  - Vectors persisted in `page_embeddings` PostgreSQL table (Phase 1 model).
  - In-memory numpy matrix built per job for fast similarity pass during categorization.
  - Redis holds NO embedding data — only transient queue pointers.
"""
import uuid
import time
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logger import logger, LoggingContext
from app.core.exceptions import AppBaseException
from app.models.embedding import PageEmbedding
from app.observability.metrics import (
    embedding_duration_seconds,
    llm_calls_total,
    llm_tokens_used_total,
    llm_cost_usd_total,
)


# ── Cost constants (USD per 1M tokens) ──────────────────────────────────────
OPENAI_COSTS: Dict[str, float] = {
    "text-embedding-3-small": 0.02 / 1_000_000,
    "text-embedding-3-large": 0.13 / 1_000_000,
}


class BudgetExceededException(AppBaseException):
    """Raised when cumulative LLM/embedding spend crosses the configured limit."""
    def __init__(self, spent: float, limit: float, job_id: str):
        super().__init__(
            f"Embedding budget exceeded for job {job_id}: "
            f"${spent:.4f} > ${limit:.4f} limit",
            context={"spent_usd": spent, "limit_usd": limit, "job_id": job_id},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Provider base
# ─────────────────────────────────────────────────────────────────────────────

class BaseEmbeddingProvider:
    async def embed_batch(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        """Returns (vectors, total_tokens). Must be implemented by subclass."""
        raise NotImplementedError

    @property
    def dimensions(self) -> int:
        raise NotImplementedError


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, model: str = "text-embedding-3-small"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=get_settings().llm.api_key)
        self.model = model

    @property
    def dimensions(self) -> int:
        return 1536 if "small" in self.model else 3072

    async def embed_batch(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        vectors = [item.embedding for item in response.data]
        tokens = response.usage.total_tokens
        return vectors, tokens


class SentenceTransformerProvider(BaseEmbeddingProvider):
    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model)

    @property
    def dimensions(self) -> int:
        return 384  # all-MiniLM-L6-v2

    async def embed_batch(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        # SentenceTransformers is synchronous — run in executor.
        # Must use get_running_loop() (get_event_loop() is deprecated in Python 3.10+
        # and raises DeprecationWarning in 3.12, will error in 3.14).
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(
            None,
            lambda: self._model.encode(texts, convert_to_numpy=True).tolist()
        )
        # Local models don't count tokens — estimate for metrics
        estimated_tokens = sum(len(t.split()) for t in texts)
        return vectors, estimated_tokens


# ─────────────────────────────────────────────────────────────────────────────
# Embedding Generator
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingGenerator:
    def __init__(self, session: AsyncSession, job_id: str):
        self.session = session
        self.job_id = job_id
        self.settings = get_settings()
        self._total_cost_usd: float = 0.0

        # Provider selection from config
        provider_name = self.settings.embedding.model
        if "openai" in self.settings.llm.provider.lower() and self.settings.llm.api_key:
            self.provider = OpenAIEmbeddingProvider(model=provider_name)
            self._cost_per_token = OPENAI_COSTS.get(provider_name, 0.0)
        else:
            logger.info("Using local SentenceTransformer provider (no OpenAI key configured).")
            self.provider = SentenceTransformerProvider()
            self._cost_per_token = 0.0

        # Per-job in-memory matrix {page_id_str: vector}
        self._matrix: Dict[str, np.ndarray] = {}

    def _check_budget(self, new_cost: float) -> None:
        self._total_cost_usd += new_cost
        limit = self.settings.llm.budget_limit_usd
        if self._total_cost_usd > limit:
            raise BudgetExceededException(self._total_cost_usd, limit, self.job_id)

    async def embed_batch(
        self,
        page_ids: List[UUID],
        texts: List[str],
    ) -> List[PageEmbedding]:
        """
        Embeds a batch of texts, persists to DB, updates in-memory matrix.
        Returns list of PageEmbedding ORM objects.
        """
        if not texts:
            return []

        with LoggingContext(job_id=self.job_id, phase="Embedding"):
            # Retry on transient API/network errors (OpenAI 500s, connection resets).
            # A single network hiccup must not discard an entire batch of 50 pages.
            max_retries = 3
            last_exc: Optional[Exception] = None
            vectors, tokens = [], 0
            for attempt in range(1, max_retries + 1):
                try:
                    t_start = time.time()
                    vectors, tokens = await self.provider.embed_batch(texts)
                    elapsed = time.time() - t_start
                    break
                except Exception as exc:
                    last_exc = exc
                    wait = 2 ** attempt
                    logger.warning(f"Embedding attempt {attempt}/{max_retries} failed: {exc}. Retrying in {wait}s.")
                    await asyncio.sleep(wait)
            else:
                raise RuntimeError(f"All {max_retries} embedding attempts failed: {last_exc}")

            # Cost tracking
            batch_cost = tokens * self._cost_per_token
            self._check_budget(batch_cost)  # raises if exceeded

            # Prometheus metrics
            llm_tokens_used_total.labels(job_id=self.job_id, model=self.settings.embedding.model).inc(tokens)
            llm_cost_usd_total.labels(job_id=self.job_id).inc(batch_cost)
            llm_calls_total.labels(job_id=self.job_id).inc()
            embedding_duration_seconds.labels(job_id=self.job_id).observe(elapsed)

            logger.info(
                "Embedded batch",
                batch_size=len(texts),
                tokens=tokens,
                cost_usd=round(batch_cost, 6),
                duration_ms=int(elapsed * 1000),
            )

            # Persist + populate in-memory matrix
            records: List[PageEmbedding] = []
            for page_id, vector in zip(page_ids, vectors):
                record = PageEmbedding(
                    id=uuid.uuid4(),
                    page_id=page_id,
                    model=self.settings.embedding.model,
                    vector=vector,
                    created_at=datetime.utcnow(),
                )
                self.session.add(record)
                self._matrix[str(page_id)] = np.array(vector, dtype=np.float32)
                records.append(record)

            await self.session.commit()
            return records

    async def load_job_matrix(self) -> None:
        """Loads all embeddings for this job into the in-memory numpy matrix.

        UUID comparison fix: self.job_id is a str; Page.job_id is UUID in PG.
        Cast with uuid.UUID() to avoid a PostgreSQL type-mismatch error.
        """
        from app.models.page import Page
        import uuid as uuid_mod
        job_uuid = uuid_mod.UUID(self.job_id) if isinstance(self.job_id, str) else self.job_id
        stmt = (
            select(PageEmbedding)
            .join(Page, PageEmbedding.page_id == Page.id)
            .where(Page.job_id == job_uuid)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        for emb in rows:
            self._matrix[str(emb.page_id)] = np.array(emb.vector, dtype=np.float32)
        logger.info(f"Loaded {len(self._matrix)} embeddings into job matrix.")

    @property
    def matrix(self) -> Dict[str, np.ndarray]:
        return self._matrix


# ─────────────────────────────────────────────────────────────────────────────
# Similarity Engine
# ─────────────────────────────────────────────────────────────────────────────

class SimilarityEngine:
    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Computes cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @staticmethod
    def find_similar_pages(
        query_vector: np.ndarray,
        matrix: Dict[str, np.ndarray],
        top_k: int = 10,
        exclude_id: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """
        Returns top-k (page_id, similarity_score) pairs sorted descending.
        O(n) — acceptable for per-job matrices up to ~50K pages.
        """
        scores: List[Tuple[str, float]] = []
        for page_id_str, vector in matrix.items():
            if page_id_str == exclude_id:
                continue
            score = SimilarityEngine.cosine_similarity(query_vector, vector)
            scores.append((page_id_str, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    @staticmethod
    def compute_centroid(vectors: List[np.ndarray]) -> np.ndarray:
        """Returns the mean vector of a list — represents a category centre."""
        if not vectors:
            raise ValueError("Cannot compute centroid of empty list.")
        stacked = np.stack(vectors, axis=0)
        return stacked.mean(axis=0)

    @staticmethod
    def cluster_embeddings(
        matrix: Dict[str, np.ndarray],
        n_clusters: int = 10,
        random_state: int = 42,
    ) -> Dict[int, List[str]]:
        """
        Uses KMeans to discover candidate topic groups when no predefined
        categories exist. Returns {cluster_id: [page_id, ...]} mapping.
        """
        from sklearn.cluster import KMeans

        if len(matrix) < n_clusters:
            n_clusters = max(1, len(matrix) // 2)

        page_ids = list(matrix.keys())
        vectors = np.stack([matrix[pid] for pid in page_ids], axis=0)

        km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init="auto")
        labels = km.fit_predict(vectors)

        clusters: Dict[int, List[str]] = {}
        for page_id, label in zip(page_ids, labels):
            clusters.setdefault(int(label), []).append(page_id)

        logger.info(
            "KMeans clustering complete",
            n_clusters=n_clusters,
            total_pages=len(page_ids),
            cluster_sizes={k: len(v) for k, v in clusters.items()},
        )
        return clusters
