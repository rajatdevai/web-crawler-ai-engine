"""
Confidence Engine

Assembles results from all three stages into a final ClassificationResult.
This is the single source of truth consumed by the API and persisted to DB.

Rules:
  - Always includes all_stage_results for full auditability.
  - needs_human_review = True whenever final_confidence < 0.7, regardless of method.
  - classification_method records which stage was decisive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.categorizer.deterministic import DeterministicResult
from app.categorizer.embedding_classifier import EmbeddingClassificationResult
from app.categorizer.llm_classifier import LLMClassificationResult, UNCATEGORIZED

HUMAN_REVIEW_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class ClassificationResult:
    final_category: str = UNCATEGORIZED
    final_confidence: float = 0.0
    classification_method: str = "none"  # "deterministic" | "embedding" | "llm" | "none"
    reasoning: str = ""
    needs_human_review: bool = True
    all_stage_results: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_category": self.final_category,
            "final_confidence": self.final_confidence,
            "classification_method": self.classification_method,
            "reasoning": self.reasoning,
            "needs_human_review": self.needs_human_review,
            "all_stage_results": self.all_stage_results,
        }


class ConfidenceEngine:
    """
    Assembles results from whichever stages ran and emits a final ClassificationResult.

    Stage precedence (highest wins):
        1. Deterministic — if matched_category is set
        2. Embedding    — if matched_category is set
        3. LLM          — always the final word if reached
    """

    def assemble(
        self,
        deterministic: Optional[DeterministicResult] = None,
        embedding: Optional[EmbeddingClassificationResult] = None,
        llm: Optional[LLMClassificationResult] = None,
    ) -> ClassificationResult:

        all_stages: Dict[str, Any] = {}

        # Serialise stage results for auditability
        if deterministic:
            all_stages["deterministic"] = {
                "matched_category": deterministic.matched_category,
                "confidence": round(deterministic.confidence, 4),
                "matched_signals": [
                    {"field": s.field, "keyword": s.keyword, "weight": s.weight}
                    for s in deterministic.matched_signals
                ],
                "skipped": deterministic.skipped,
            }

        if embedding:
            all_stages["embedding"] = {
                "matched_category": embedding.matched_category,
                "confidence": round(embedding.confidence, 4),
                "similarity_score": round(embedding.similarity_score, 4),
                "centroid_page_count": embedding.centroid_page_count,
                "used_clustering": embedding.used_clustering,
            }

        if llm:
            all_stages["llm"] = {
                "matched_category": llm.matched_category,
                "confidence": round(llm.confidence, 4),
                "reasoning": llm.reasoning,
                "needs_human_review": llm.needs_human_review,
                "prompt_tokens": llm.prompt_tokens,
                "completion_tokens": llm.completion_tokens,
                "model_used": llm.model_used,
                "latency_ms": llm.latency_ms,
                "cost_usd": llm.cost_usd,
                "injection_fields_sanitized": llm.injection_fields_sanitized,
            }

        # ── Determine winning result ─────────────────────────────────────
        final_category = UNCATEGORIZED
        final_confidence = 0.0
        method = "none"
        reasoning = ""
        llm_review_flag = False

        if deterministic and deterministic.matched_category:
            final_category = deterministic.matched_category
            final_confidence = deterministic.confidence
            method = "deterministic"
            reasoning = (
                f"Matched via {len(deterministic.matched_signals)} signals: "
                + ", ".join(f"{s.field}={s.keyword}" for s in deterministic.matched_signals[:3])
            )

        elif embedding and embedding.matched_category:
            final_category = embedding.matched_category
            final_confidence = embedding.confidence
            method = "embedding" if not embedding.used_clustering else "embedding_clustering"
            reasoning = (
                f"Cosine similarity {embedding.similarity_score:.3f} against "
                f"centroid from {embedding.centroid_page_count} pages"
                if not embedding.used_clustering
                else "KMeans cluster assignment (no centroids yet)"
            )

        elif llm and llm.matched_category:
            final_category = llm.matched_category
            final_confidence = llm.confidence
            method = "llm"
            reasoning = llm.reasoning
            llm_review_flag = llm.needs_human_review

        # needs_human_review: LLM already set it OR confidence too low
        needs_human_review = llm_review_flag or (final_confidence < HUMAN_REVIEW_CONFIDENCE_THRESHOLD)

        return ClassificationResult(
            final_category=final_category,
            final_confidence=final_confidence,
            classification_method=method,
            reasoning=reasoning,
            needs_human_review=needs_human_review,
            all_stage_results=all_stages,
        )
