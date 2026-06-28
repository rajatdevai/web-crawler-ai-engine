"""
Embedding Input Builder

Constructs a semantically weighted string from a PageDocument for embedding.
Ordering is deliberate — title carries the most semantic weight.
"""
from typing import Any, Dict, List, Optional

MAX_INPUT_CHARS = 8000


def build_embedding_input(page_document: Dict[str, Any]) -> str:
    """
    Constructs a carefully weighted semantic string from a PageDocument.

    Weight priority (high → low):
        1. Title (repeated twice — gives 2x TF weight in embedding space)
        2. Meta description
        3. H1 headers
        4. H2 headers (joined)
        5. First 500 words of clean body text
        6. Breadcrumb path (encodes page position in site hierarchy)
        7. Schema.org product/service names (explicit business signals)

    Rules:
        - Never send raw HTML.
        - Never send boilerplate text (already removed upstream by Phase 5).
        - Truncate to MAX_INPUT_CHARS before API call.
    """
    parts: List[str] = []

    # 1. Title × 2 (semantic amplification)
    title = (page_document.get("title") or "").strip()
    if title:
        parts.append(title)
        parts.append(title)  # repeated intentionally

    # 2. Meta description
    meta = (page_document.get("meta_description") or "").strip()
    if meta:
        parts.append(meta)

    # 3. H1 tags
    for h1 in page_document.get("h1_tags") or []:
        h1 = h1.strip()
        if h1:
            parts.append(h1)

    # 4. H2 tags (joined, not repeated)
    h2_text = " | ".join(
        h.strip() for h in (page_document.get("h2_tags") or []) if h.strip()
    )
    if h2_text:
        parts.append(h2_text)

    # 5. First 500 words of body text
    body = (page_document.get("body_text") or "").strip()
    if body:
        words = body.split()
        parts.append(" ".join(words[:500]))

    # 6. Breadcrumb path
    breadcrumbs = page_document.get("breadcrumbs") or []
    if breadcrumbs:
        parts.append(" > ".join(b.strip() for b in breadcrumbs if b.strip()))

    # 7. Schema.org product / service names
    metadata = page_document.get("metadata") or {}
    schema_names: List[str] = []
    for entity_list_key in ("products", "services"):
        for entity in metadata.get(entity_list_key) or []:
            name = (entity.get("name") or "").strip()
            if name:
                schema_names.append(name)
    if schema_names:
        parts.append("Products/Services: " + ", ".join(schema_names))

    # Guard: nothing was extracted (empty / boilerplate-only page)
    if not parts:
        return ""

    combined = "\n".join(parts)

    # Truncate at word boundary so the model never receives a mid-word fragment.
    # Slicing raw chars could cut "manufacturing" → "manufacturi" which shifts semantics.
    if len(combined) > MAX_INPUT_CHARS:
        truncated = combined[:MAX_INPUT_CHARS]
        last_space = truncated.rfind(" ")
        combined = truncated[:last_space] if last_space > 0 else truncated

    return combined
