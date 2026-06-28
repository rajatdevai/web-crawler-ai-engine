import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup


@dataclass
class ExtractedMetadata:
    products: List[Dict[str, Any]] = field(default_factory=list)
    services: List[Dict[str, Any]] = field(default_factory=list)
    faqs: List[Dict[str, str]] = field(default_factory=list)
    articles: List[Dict[str, Any]] = field(default_factory=list)
    reviews: List[Dict[str, Any]] = field(default_factory=list)
    organizations: List[Dict[str, Any]] = field(default_factory=list)
    offers: List[Dict[str, Any]] = field(default_factory=list)
    raw_schemas: List[Dict[str, Any]] = field(default_factory=list)


class MetadataExtractor:
    def extract(self, html: str) -> ExtractedMetadata:
        soup = BeautifulSoup(html, "lxml")
        meta = ExtractedMetadata()

        # Parse all JSON-LD blocks
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    self._process_schema(data, meta)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            self._process_schema(item, meta)
            except (json.JSONDecodeError, TypeError):
                pass

        return meta

    def _process_schema(self, data: Dict[str, Any], meta: ExtractedMetadata) -> None:
        meta.raw_schemas.append(data)
        schema_type = data.get("@type", "")

        # Handle array types (e.g., "@type": ["Product", "Thing"])
        if isinstance(schema_type, list):
            schema_type = schema_type[0] if schema_type else ""

        if schema_type == "Product":
            meta.products.append({
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "sku": data.get("sku", ""),
                "brand": self._nested(data, "brand", "name"),
                "image": data.get("image", ""),
            })

        elif schema_type == "Service":
            meta.services.append({
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "provider": self._nested(data, "provider", "name"),
            })

        elif schema_type == "FAQPage":
            for item in data.get("mainEntity", []):
                q = item.get("name", "") or item.get("question", {}).get("name", "")
                a = self._nested(item, "acceptedAnswer", "text")
                if q:
                    meta.faqs.append({"question": q, "answer": a})

        elif schema_type in ("Article", "BlogPosting", "NewsArticle"):
            meta.articles.append({
                "headline": data.get("headline", ""),
                "author": self._nested(data, "author", "name"),
                "datePublished": data.get("datePublished", ""),
                "dateModified": data.get("dateModified", ""),
                "description": data.get("description", ""),
            })

        elif schema_type == "Review":
            meta.reviews.append({
                "author": self._nested(data, "author", "name"),
                "rating": self._nested(data, "reviewRating", "ratingValue"),
                "body": data.get("reviewBody", ""),
            })

        elif schema_type == "Organization":
            meta.organizations.append({
                "name": data.get("name", ""),
                "url": data.get("url", ""),
                "description": data.get("description", ""),
                "telephone": data.get("telephone", ""),
                "address": self._nested(data, "address", "streetAddress"),
            })

        elif schema_type == "Offer":
            meta.offers.append({
                "price": data.get("price", ""),
                "priceCurrency": data.get("priceCurrency", ""),
                "availability": data.get("availability", ""),
            })

        # Recurse into graph nodes
        for graph_item in data.get("@graph", []):
            if isinstance(graph_item, dict):
                self._process_schema(graph_item, meta)

    def _nested(self, data: dict, *keys: str) -> str:
        """Safely extract nested dict values."""
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key, "")
            else:
                return ""
        return str(current) if current else ""
