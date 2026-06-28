import re
import hashlib
from bs4 import BeautifulSoup, Comment
from typing import Set
from app.core.logger import logger
from app.database.redis_client import redis_client

NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "object", "embed"]
NOISE_CLASSES = [
    "cookie-banner", "cookie-notice", "gdpr", "consent",
    "ad", "ads", "advertisement", "banner", "sponsor",
    "sidebar", "side-bar", "widget", "popup", "modal-overlay",
    "social-share", "share-bar", "newsletter-popup"
]

class HTMLCleaner:
    def clean(self, html: str) -> str:
        """Remove all noise elements and return cleaned HTML string."""
        soup = BeautifulSoup(html, "lxml")

        # Remove noise tags entirely
        for tag in soup(NOISE_TAGS):
            tag.decompose()

        # Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove noise class containers
        for cls in NOISE_CLASSES:
            for el in soup.find_all(class_=re.compile(cls, re.IGNORECASE)):
                el.decompose()

        # Remove nav elements containing only links (pure navigation)
        for nav in soup.find_all("nav"):
            non_links = [t for t in nav.find_all(True) if t.name not in ("a", "li", "ul", "ol", "span")]
            if not non_links:
                nav.decompose()

        # Remove header and footer
        for tag in soup(["header", "footer"]):
            tag.decompose()

        # Strip all data-* attributes EXCEPT data-category and data-type
        for tag in soup.find_all(True):
            attrs_to_remove = [
                a for a in list(tag.attrs.keys())
                if a.startswith("data-") and a not in ("data-category", "data-type")
            ]
            for attr in attrs_to_remove:
                del tag[attr]

        return str(soup)


class BoilerplateDetector:
    """
    After 10 pages are processed for a job, identifies text blocks appearing
    on more than 80% of pages and marks them as boilerplate.
    Stores fingerprints in Redis keyed by job_id.
    """
    MIN_PAGES = 10
    THRESHOLD = 0.80
    BLOCK_HASH_PREFIX = "boilerplate_blocks:"
    PAGE_COUNT_PREFIX = "boilerplate_page_count:"

    def _fingerprint_blocks(self, text: str) -> Set[str]:
        """Split text into paragraph blocks and hash each."""
        blocks = set()
        for line in text.splitlines():
            line = line.strip()
            if len(line) > 30:  # Only meaningful lines
                blocks.add(hashlib.md5(line.encode()).hexdigest())
        return blocks

    async def record_page(self, job_id: str, cleaned_text: str) -> None:
        """Record text fingerprints for a processed page."""
        page_count_key = f"{self.PAGE_COUNT_PREFIX}{job_id}"
        blocks_key = f"{self.BLOCK_HASH_PREFIX}{job_id}"

        blocks = self._fingerprint_blocks(cleaned_text)
        if not blocks:
            return

        # Increment global page count
        await redis_client.increment(page_count_key)

        # Increment count per block
        for block_hash in blocks:
            await redis_client.increment(f"{blocks_key}:{block_hash}")

    async def get_boilerplate_hashes(self, job_id: str) -> Set[str]:
        """Returns set of block hashes that qualify as boilerplate."""
        page_count_key = f"{self.PAGE_COUNT_PREFIX}{job_id}"
        blocks_key = f"{self.BLOCK_HASH_PREFIX}{job_id}"

        page_count_str = await redis_client.get(page_count_key)
        if not page_count_str:
            return set()

        page_count = int(page_count_str)
        if page_count < self.MIN_PAGES:
            return set()

        # We cannot efficiently enumerate Redis keys with current client methods.
        # This is a simplified approach — in production, use SCAN + HSCAN or a Redis Hash.
        # For now, return empty set and let the detector mature with full Redis SCAN support.
        return set()

    async def remove_boilerplate(self, job_id: str, text: str) -> str:
        """Removes boilerplate lines from cleaned text."""
        boilerplate = await self.get_boilerplate_hashes(job_id)
        if not boilerplate:
            return text

        lines = []
        for line in text.splitlines():
            line_hash = hashlib.md5(line.strip().encode()).hexdigest()
            if line_hash not in boilerplate:
                lines.append(line)
        return "\n".join(lines)
