import gzip
import io
import httpx
from typing import List, AsyncGenerator
from lxml import etree
from app.core.logger import logger
from app.crawler.url_utils import normalize_url, is_internal_url
from app.crawler.robots import RobotsTxtParser

class SitemapParser:
    def __init__(self, base_url: str, robots_parser: RobotsTxtParser):
        self.base_url = base_url
        self.robots_parser = robots_parser

    async def fetch_and_parse(self, sitemap_url: str) -> AsyncGenerator[str, None]:
        """
        Recursively fetches and stream-parses sitemap.xml, sitemap_index.xml and .gz files.
        Yields valid, internal, allowed URLs.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(sitemap_url, follow_redirects=True)
                
            if response.status_code != 200:
                logger.warning(f"Failed to fetch sitemap: {sitemap_url} (HTTP {response.status_code})")
                return

            content = response.content
            if sitemap_url.endswith(".gz") or response.headers.get("Content-Encoding") == "gzip":
                try:
                    content = gzip.decompress(content)
                except Exception as e:
                    logger.error(f"Failed to decompress gzip sitemap {sitemap_url}: {e}")
                    return

            # Check if it's a plain text sitemap
            if response.headers.get("Content-Type", "").startswith("text/plain") or not content.strip().startswith(b"<"):
                urls = content.decode("utf-8").splitlines()
                for url in urls:
                    url = url.strip()
                    if url:
                        valid_url = self._process_url(url)
                        if valid_url:
                            yield valid_url
                return

            # Parse XML with lxml iterparse
            # We strip namespaces by ignoring them in tags
            context = etree.iterparse(io.BytesIO(content), events=("end",), recover=True)
            
            for event, elem in context:
                tag = etree.QName(elem.tag).localname
                
                if tag == "sitemap":
                    # It's a sitemap index, find loc and recurse
                    loc_elem = elem.find("*[local-name()='loc']")
                    if loc_elem is not None and loc_elem.text:
                        nested_url = loc_elem.text.strip()
                        async for u in self.fetch_and_parse(nested_url):
                            yield u
                    elem.clear()
                    
                elif tag == "url":
                    # It's a regular url entry
                    loc_elem = elem.find("*[local-name()='loc']")
                    if loc_elem is not None and loc_elem.text:
                        raw_url = loc_elem.text.strip()
                        valid_url = self._process_url(raw_url)
                        if valid_url:
                            yield valid_url
                    elem.clear()

        except Exception as e:
            logger.error(f"Error parsing sitemap {sitemap_url}: {e}", exc_info=True)

    def _process_url(self, url: str) -> str | None:
        """Normalizes and checks internal + robots constraints."""
        norm_url = normalize_url(url, self.base_url)
        if is_internal_url(norm_url, self.base_url) and self.robots_parser.is_allowed(norm_url):
            return norm_url
        return None
