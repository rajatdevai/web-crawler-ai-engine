import urllib.robotparser
import urllib.parse
from typing import List, Optional
import httpx
from app.core.logger import logger
from app.database.redis_client import redis_client
from app.core.config import get_settings

class RobotsTxtParser:
    CACHE_PREFIX = "robots_txt:"
    CACHE_TTL = 3600 # 1 hour

    def __init__(self, domain_url: str):
        parsed_domain = urllib.parse.urlparse(domain_url)
        self.base_url = f"{parsed_domain.scheme}://{parsed_domain.netloc}"
        self.robots_url = f"{self.base_url}/robots.txt"
        self.parser = urllib.robotparser.RobotFileParser()
        self.parser.set_url(self.robots_url)
        self.settings = get_settings()

    async def fetch_and_parse(self) -> None:
        """Fetches robots.txt, respects cache, and parses it."""
        cache_key = f"{self.CACHE_PREFIX}{self.base_url}"
        
        cached_content = await redis_client.get(cache_key)
        
        if cached_content is not None:
            self._parse_content(cached_content)
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    self.robots_url,
                    headers={"User-Agent": self.settings.crawler.user_agent},
                    follow_redirects=True
                )
            
            if response.status_code == 200:
                content = response.text
            elif response.status_code in (404, 403, 500, 502, 503, 504):
                # Fail open: Assume full crawl permission
                logger.warning(f"robots.txt returned {response.status_code} for {self.base_url}. Assuming full permission.")
                content = ""
            else:
                content = ""
                
        except httpx.RequestError as e:
            logger.warning(f"robots.txt fetch failed for {self.base_url}: {e}. Assuming full permission.")
            content = ""

        # Cache the content
        await redis_client.set_with_ttl(cache_key, content, self.CACHE_TTL)
        self._parse_content(content)

    def _parse_content(self, content: str) -> None:
        lines = content.splitlines()
        self.parser.parse(lines)

    def is_allowed(self, url: str) -> bool:
        """Checks if the URL is allowed to be crawled by the configured User-Agent."""
        if not self.settings.crawler.respect_robots_txt:
            return True
            
        try:
            return self.parser.can_fetch(self.settings.crawler.user_agent, url)
        except Exception as e:
            logger.error(f"Error evaluating robots.txt for {url}: {e}")
            return True

    def get_sitemaps(self) -> List[str]:
        """Extracts Sitemap URLs from robots.txt."""
        return self.parser.site_maps() or []
