"""
Stage 2 — Embedding Classifier

Computes cosine similarity between a page's embedding and all category centroids.

Rules:
  - ZERO LLM API calls. Uses pre-computed embeddings only.
  - Category centroids are maintained by CategoryService and updated every 10 new pages.
  - Falls back to KMeans cluster assignments if no centroids exist yet.
  - Returns EmbeddingClassificationResult. If confidence < threshold, Stage 3 handles it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from uuid import UUID

import numpy as np

from app.core.config import get_settings
from app.core.logger import logger
from app.embeddings.generator import SimilarityEngine


@dataclass
class EmbeddingClassificationResult:
    matched_category: Optional[str] = None
    confidence: float = 0.0
    similarity_score: float = 0.0
    centroid_page_count: int = 0   # how many pages contributed to the centroid
    used_clustering: bool = False  # True if KMeans fallback was used


class EmbeddingClassifier:
    def __init__(
        self,
        # category_name -> centroid numpy vector
        centroids: Dict[str, np.ndarray],
        centroid_counts: Dict[str, int],
        # fallback: KMeans cluster_id -> [page_id_str, ...]
        cluster_map: Optional[Dict[int, List[str]]] = None,
        cluster_labels: Optional[Dict[int, str]] = None,
    ):
        self.centroids = centroids
        self.centroid_counts = centroid_counts
        self.cluster_map = cluster_map or {}
        self.cluster_labels = cluster_labels or {}
        self.settings = get_settings()
        self.threshold = self.settings.classification.embedding_similarity_threshold

    def classify(
        self,
        page_embedding: np.ndarray,
        page_id: Optional[str] = None,
    ) -> EmbeddingClassificationResult:
        """
        Cosine similarity against all known category centroids.
        Falls back to KMeans cluster assignment if no centroids exist.
        Zero API calls.
        """
        # --- Primary: centroid similarity ---
        if self.centroids:
            best_cat, best_score = self._best_centroid_match(page_embedding)

            logger.debug(
                "Embedding classification via centroids",
                best_category=best_cat,
                similarity=round(best_score, 4),
                threshold=self.threshold,
            )

            if best_score >= self.threshold:
                return EmbeddingClassificationResult(
                    matched_category=best_cat,
                    confidence=best_score,
                    similarity_score=best_score,
                    centroid_page_count=self.centroid_counts.get(best_cat, 0),
                )

            # Below threshold — return partial so Stage 3 knows the closest category
            return EmbeddingClassificationResult(
                matched_category=None,
                confidence=best_score,
                similarity_score=best_score,
                centroid_page_count=self.centroid_counts.get(best_cat, 0),
            )

        # --- Fallback: KMeans cluster assignment ---
        if self.cluster_map and page_id:
            for cluster_id, page_ids in self.cluster_map.items():
                if page_id in page_ids:
                    label = self.cluster_labels.get(cluster_id, f"Cluster-{cluster_id}")
                    logger.debug(f"KMeans fallback: page {page_id} → cluster {cluster_id} ({label})")
                    # Cluster assignments have inherently lower confidence (~0.5)
                    return EmbeddingClassificationResult(
                        matched_category=label,
                        confidence=0.5,
                        similarity_score=0.5,
                        used_clustering=True,
                    )

        logger.debug("No centroids or cluster data available for embedding classification.")
        return EmbeddingClassificationResult()

    def _best_centroid_match(self, vector: np.ndarray) -> Tuple[str, float]:
        """Returns (category_name, similarity) for the best matching centroid."""
        best_cat = ""
        best_score = -1.0
        for cat_name, centroid in self.centroids.items():
            score = SimilarityEngine.cosine_similarity(vector, centroid)
            if score > best_score:
                best_score = score
                best_cat = cat_name
        return best_cat, best_score
