"""
Stage 3 — LLM Classifier

Invoked ONLY when Stage 1 and Stage 2 confidence are both below thresholds.

Security: All text fields pass through PromptInjectionScanner before LLM sees them.
Contract: LLM must return strict JSON. One retry with explicit format reminder.
Fallback: Two failed attempts → UNCATEGORIZED + needs_human_review = True.
Cost: Every call tracked (prompt tokens, completion tokens, latency, USD cost).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.logger import logger, LoggingContext
from app.core.exceptions import AppBaseException

# Prompt injection patterns
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(previous|prior|above|all)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(your|the|all)\s+(instructions?|rules?|system\s+prompt)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"new\s+(system\s+)?prompt:", re.IGNORECASE),
    re.compile(r"(act|behave)\s+as\s+(if\s+)?you\s+(are|were)", re.IGNORECASE),
    re.compile(r"\{\s*[\"\']?(category|confidence|reasoning)[\"\']?\s*:", re.IGNORECASE),  # embedded JSON hijack
    re.compile(r"[\u202e\u200f\u200e\u202a-\u202d]"),  # bidirectional override chars
]

SANITIZE_PLACEHOLDER = "[CONTENT REMOVED: INJECTION PATTERN DETECTED]"

UNCATEGORIZED = "UNCATEGORIZED"

SYSTEM_PROMPT = """You are an expert content categorization AI for a supplement manufacturing website.
Analyze the provided page content and return ONLY valid JSON with exactly these fields:
{
  "category": "string (e.g. Gummies, Capsules, Blog, About, Services)",
  "confidence": 0.85,
  "reasoning": "One sentence explanation",
  "needs_human_review": false
}
Do not include any text outside the JSON object. Do not include markdown code fences."""

FORMAT_REMINDER = """Your previous response was not valid JSON. 
You MUST return ONLY a JSON object with exactly these four fields:
category (string), confidence (float 0-1), reasoning (string), needs_human_review (boolean).
No markdown, no explanation, no code fences. Only the raw JSON object."""


@dataclass
class LLMClassificationResult:
    matched_category: Optional[str] = None
    confidence: float = 0.0
    reasoning: str = ""
    needs_human_review: bool = False
    # Cost audit trail
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_used: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    injection_fields_sanitized: List[str] = field(default_factory=list)


def scan_and_sanitize(text: str, field_name: str, sanitized_fields: List[str]) -> str:
    """Scans text for prompt injection patterns. Replaces with placeholder if detected."""
    if not text:
        return text
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning(
                "Prompt injection pattern detected",
                field=field_name,
                pattern=pattern.pattern[:50],
            )
            sanitized_fields.append(field_name)
            return SANITIZE_PLACEHOLDER
    return text


class LLMClassifier:
    def __init__(self):
        self.settings = get_settings()
        self.model = self.settings.llm.model
        self._cost_per_input_token = 0.0000015  # GPT-4o-mini input
        self._cost_per_output_token = 0.000006  # GPT-4o-mini output

    async def classify(self, page_document: Dict[str, Any]) -> LLMClassificationResult:
        """Runs LLM classification with injection protection and one retry."""
        sanitized_fields: List[str] = []

        # ── Build minimal context (only what the LLM needs) ──────────────
        title = scan_and_sanitize(page_document.get("title", ""), "title", sanitized_fields)
        meta = scan_and_sanitize(page_document.get("meta_description", ""), "meta_description", sanitized_fields)
        h1 = scan_and_sanitize(
            " | ".join((page_document.get("h1_tags") or [])[:3]), "h1_tags", sanitized_fields
        )
        h2s = scan_and_sanitize(
            " | ".join((page_document.get("h2_tags") or [])[:3]), "h2_tags", sanitized_fields
        )
        breadcrumbs = scan_and_sanitize(
            " > ".join(page_document.get("breadcrumbs") or []), "breadcrumbs", sanitized_fields
        )
        # First 300 words of body
        body_words = (page_document.get("body_text") or "").split()[:300]
        body_snippet = scan_and_sanitize(" ".join(body_words), "body_text", sanitized_fields)

        schema_type = ""
        for sd in (page_document.get("structured_data") or []):
            if sd.get("@type"):
                schema_type = str(sd["@type"])
                break

        user_content = (
            f"Title: {title}\n"
            f"Meta Description: {meta}\n"
            f"H1: {h1}\n"
            f"H2s: {h2s}\n"
            f"Breadcrumbs: {breadcrumbs}\n"
            f"Schema.org Type: {schema_type}\n"
            f"Body (first 300 words):\n{body_snippet}"
        )

        # ── Attempt 1 ────────────────────────────────────────────────────
        result = await self._call_llm(
            user_content=user_content,
            sanitized_fields=sanitized_fields,
            is_retry=False,
        )
        if result is not None:
            return result

        # ── Attempt 2 (with format reminder) ─────────────────────────────
        logger.warning("LLM response was invalid JSON on attempt 1. Retrying with format reminder.")
        result = await self._call_llm(
            user_content=user_content,
            sanitized_fields=sanitized_fields,
            is_retry=True,
        )
        if result is not None:
            return result

        # ── Both attempts failed ─────────────────────────────────────────
        logger.error("LLM classifier failed both attempts. Marking page as UNCATEGORIZED + needs_human_review.")
        return LLMClassificationResult(
            matched_category=UNCATEGORIZED,
            confidence=0.0,
            reasoning="LLM failed to return valid JSON on both attempts.",
            needs_human_review=True,
            injection_fields_sanitized=sanitized_fields,
        )

    async def _call_llm(
        self,
        user_content: str,
        sanitized_fields: List[str],
        is_retry: bool,
    ) -> Optional[LLMClassificationResult]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.settings.llm.api_key)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if is_retry:
            messages.append({"role": "assistant", "content": "I need to correct my output."})
            messages.append({"role": "user", "content": FORMAT_REMINDER + "\n\n" + user_content})
        else:
            messages.append({"role": "user", "content": user_content})

        t_start = time.time()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,    # deterministic output for classification
                max_tokens=256,     # JSON response is small — cap to prevent verbose failures
                response_format={"type": "json_object"},  # enforce JSON mode on supported models
            )
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            return None

        latency_ms = int((time.time() - t_start) * 1000)
        usage = response.usage
        cost = (
            usage.prompt_tokens * self._cost_per_input_token +
            usage.completion_tokens * self._cost_per_output_token
        )

        raw = response.choices[0].message.content or ""

        # Parse and validate JSON contract
        parsed = self._parse_response(raw)
        if parsed is None:
            return None

        return LLMClassificationResult(
            matched_category=parsed.get("category", UNCATEGORIZED),
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=str(parsed.get("reasoning", "")),
            needs_human_review=bool(parsed.get("needs_human_review", False)),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            model_used=self.model,
            latency_ms=latency_ms,
            cost_usd=round(cost, 8),
            injection_fields_sanitized=sanitized_fields,
        )

    def _parse_response(self, raw: str) -> Optional[Dict]:
        """Strict contract parser. Returns None on any violation."""
        try:
            parsed = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning(f"LLM returned non-JSON: {raw[:200]}")
            return None

        required = {"category", "confidence", "reasoning", "needs_human_review"}
        if not required.issubset(parsed.keys()):
            missing = required - parsed.keys()
            logger.warning(f"LLM JSON missing required fields: {missing}")
            return None

        # Type coercion + guard
        try:
            parsed["confidence"] = max(0.0, min(1.0, float(parsed["confidence"])))
            parsed["needs_human_review"] = bool(parsed["needs_human_review"])
            parsed["category"] = str(parsed["category"])
            parsed["reasoning"] = str(parsed["reasoning"])
        except (TypeError, ValueError) as e:
            logger.warning(f"LLM JSON field type error: {e}")
            return None

        return parsed
