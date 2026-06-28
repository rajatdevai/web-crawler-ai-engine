import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from app.crawler.url_utils import normalize_url, is_internal_url

DOWNLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".tar", ".gz", ".csv"}
PAGINATION_PATTERNS = re.compile(r'[?&](page|p|pg)=\d+|/page/\d+|/p/\d+', re.IGNORECASE)


@dataclass
class ExtractedLink:
    href: str
    anchor_text: str
    rel: str
    is_internal: bool
    link_type: str  # navigation | content | pagination | download | external


@dataclass
class LinkExtractionResult:
    links: List[ExtractedLink] = field(default_factory=list)

    @property
    def internal_links(self) -> List[ExtractedLink]:
        return [l for l in self.links if l.is_internal]

    @property
    def external_links(self) -> List[ExtractedLink]:
        return [l for l in self.links if not l.is_internal]

    @property
    def pagination_links(self) -> List[ExtractedLink]:
        return [l for l in self.links if l.link_type == "pagination"]

    @property
    def download_links(self) -> List[ExtractedLink]:
        return [l for l in self.links if l.link_type == "download"]


class LinkExtractor:
    def extract(self, html: str, base_url: str, seed_url: str) -> LinkExtractionResult:
        soup = BeautifulSoup(html, "lxml")
        result = LinkExtractionResult()
        seen = set()

        for a_tag in soup.find_all("a", href=True):
            raw_href = a_tag.get("href", "").strip()
            if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            norm_href = normalize_url(raw_href, base_url)
            if not norm_href or norm_href in seen:
                continue
            seen.add(norm_href)

            anchor_text = a_tag.get_text(strip=True)
            rel_attr = " ".join(a_tag.get("rel", []))
            internal = is_internal_url(norm_href, seed_url)

            link_type = self._classify(norm_href, rel_attr, internal, soup, a_tag)

            result.links.append(ExtractedLink(
                href=norm_href,
                anchor_text=anchor_text,
                rel=rel_attr,
                is_internal=internal,
                link_type=link_type
            ))

        return result

    def _classify(self, href: str, rel: str, is_internal: bool, soup, a_tag) -> str:
        if not is_internal:
            return "external"

        # Pagination detection
        if "next" in rel or "prev" in rel or PAGINATION_PATTERNS.search(href):
            return "pagination"

        # Download detection
        parsed = urlparse(href)
        if any(parsed.path.lower().endswith(ext) for ext in DOWNLOAD_EXTENSIONS):
            return "download"

        # Navigation detection: link is inside nav or header, or has no meaningful text
        parent_tags = [p.name for p in a_tag.parents]
        if "nav" in parent_tags or "header" in parent_tags:
            return "navigation"

        return "content"
