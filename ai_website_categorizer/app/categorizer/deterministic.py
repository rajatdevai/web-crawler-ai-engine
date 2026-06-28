"""
Stage 1 — Deterministic Classifier

Scores URL path segments, title, h1, breadcrumbs, schema.org type,
and meta keywords against a configurable signal dictionary.

Rules:
  - ZERO external API calls. Ever.
  - Returns DeterministicResult with matched_category and all contributing signals.
  - If confidence < DETERMINISTIC_CONFIDENCE_THRESHOLD, returns no category — Stage 2 handles it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.logger import logger

# Default signal vocabulary — overridable per job
DEFAULT_SIGNAL_DICT: Dict[str, List[str]] = {
    "Gummies": ["gummy", "gummies", "chewable", "chew", "pectin", "gelatin"],
    "Capsules": ["capsule", "capsules", "softgel", "softgels", "hard shell"],
    "Powders": ["powder", "powders", "blend", "mix", "shake", "scoop"],
    "Liquids": ["liquid", "tincture", "syrup", "drops", "fluid", "oil"],
    "Tablets": ["tablet", "tablets", "pill", "pills", "lozenge"],
    "Private Label": ["private label", "white label", "custom formula", "your brand"],
    "Contract Manufacturing": ["contract manufacturing", "contract manufacturer", "toll manufacturing"],
    "Regulatory": ["fda", "gmp", "cgmp", "nsf", "usp", "regulation", "compliance", "certification"],
    "Blog": ["blog", "article", "news", "post", "update", "insight", "guide", "tips"],
    "About": ["about", "our story", "mission", "who we are", "history", "team"],
    "Contact": ["contact", "reach us", "get in touch", "support", "help", "faq"],
    "Products": ["product", "products", "shop", "catalog", "offering", "supplement"],
    "Services": ["service", "services", "solution", "solutions", "capability", "capabilities"],
}

# URL path segments that are strong category signals
UTILITY_PATHS = {"/login", "/cart", "/checkout", "/account", "/search", "/404", "/sitemap"}


@dataclass
class SignalMatch:
    field: str          # e.g. "url_path", "title", "h1"
    keyword: str        # the matched keyword
    category: str       # which category it contributes to
    weight: float       # signal weight


@dataclass
class DeterministicResult:
    matched_category: Optional[str] = None
    confidence: float = 0.0
    matched_signals: List[SignalMatch] = field(default_factory=list)
    skipped: bool = False  # True if page is a utility page (login/cart/etc.)


class DeterministicClassifier:
    def __init__(self, signal_dict: Optional[Dict[str, List[str]]] = None):
        self.signal_dict = signal_dict or DEFAULT_SIGNAL_DICT
        self.settings = get_settings()
        self.threshold = self.settings.classification.deterministic_confidence_threshold

    def classify(self, page_document: Dict[str, Any], page_url: str = "") -> DeterministicResult:
        """
        Scores the page against the signal dictionary.
        Returns a DeterministicResult. Zero API calls.
        """
        # Skip utility pages immediately
        path = urlparse(page_url).path.lower()
        if any(path.startswith(up) for up in UTILITY_PATHS):
            return DeterministicResult(skipped=True)

        scores: Dict[str, float] = {}
        signals: List[SignalMatch] = []

        # --- Signal extraction with weights ---
        # URL path segments are strong signals (weight=1.5)
        path_text = " ".join(path.replace("/", " ").replace("-", " ").replace("_", " ").split())
        self._score_text(path_text, "url_path", weight=1.5, scores=scores, signals=signals)

        # Title (weight=1.4)
        title = (page_document.get("title") or "").lower()
        self._score_text(title, "title", weight=1.4, scores=scores, signals=signals)

        # H1 (weight=1.3)
        for h1 in (page_document.get("h1_tags") or []):
            self._score_text(h1.lower(), "h1", weight=1.3, scores=scores, signals=signals)

        # Breadcrumbs (weight=1.2)
        for crumb in (page_document.get("breadcrumbs") or []):
            self._score_text(crumb.lower(), "breadcrumb", weight=1.2, scores=scores, signals=signals)

        # schema.org @type (weight=1.5 — explicit business declaration)
        for sd in (page_document.get("structured_data") or []):
            schema_type = sd.get("@type", "")
            if schema_type:
                self._score_text(schema_type.lower(), "schema_type", weight=1.5, scores=scores, signals=signals)

        # Meta keywords (weight=1.1)
        meta_kw = page_document.get("og_data", {}).get("keywords", "")
        if meta_kw:
            self._score_text(meta_kw.lower(), "meta_keywords", weight=1.1, scores=scores, signals=signals)

        # H2 tags (weight=1.0)
        for h2 in (page_document.get("h2_tags") or [])[:5]:
            self._score_text(h2.lower(), "h2", weight=1.0, scores=scores, signals=signals)

        if not scores:
            return DeterministicResult()

        # Normalise scores to [0, 1]
        max_possible = sum(1.5 * len(kws) for kws in self.signal_dict.values())
        best_cat = max(scores, key=scores.__getitem__)
        best_raw = scores[best_cat]
        confidence = min(best_raw / max(max_possible * 0.05, 1.0), 1.0)

        cat_signals = [s for s in signals if s.category == best_cat]

        logger.debug(
            "Deterministic classification",
            best_category=best_cat,
            confidence=round(confidence, 3),
            signals=[f"{s.field}:{s.keyword}" for s in cat_signals],
        )

        if confidence >= self.threshold:
            return DeterministicResult(
                matched_category=best_cat,
                confidence=confidence,
                matched_signals=cat_signals,
            )

        # Below threshold — return partial result so Stage 2 can see what we found
        return DeterministicResult(
            matched_category=None,
            confidence=confidence,
            matched_signals=cat_signals,
        )

    def _score_text(
        self,
        text: str,
        field_name: str,
        weight: float,
        scores: Dict[str, float],
        signals: List[SignalMatch],
    ) -> None:
        if not text:
            return
        for category, keywords in self.signal_dict.items():
            for kw in keywords:
                # Whole-word match to avoid "cap" matching "capsule"
                if re.search(rf'\b{re.escape(kw)}\b', text, re.IGNORECASE):
                    scores[category] = scores.get(category, 0.0) + weight
                    signals.append(SignalMatch(
                        field=field_name,
                        keyword=kw,
                        category=category,
                        weight=weight,
                    ))
