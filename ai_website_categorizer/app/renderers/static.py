import time
import httpx
from bs4 import BeautifulSoup
from app.renderers.base import BaseRenderer, RenderResult
from app.renderers.tech_detection import TechDetector
from app.models.page import RenderMethod
from app.core.config import get_settings
from app.core.logger import logger

class StaticRenderer(BaseRenderer):
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            timeout=self.settings.crawler.request_timeout,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": self.settings.crawler.user_agent}
        )

    async def render(self, url: str) -> RenderResult:
        start_time = time.time()
        result = RenderResult(render_method=RenderMethod.STATIC)
        
        try:
            response = await self.client.get(url)
            result.http_status = response.status_code
            result.final_url = str(response.url)
            
            if response.status_code == 200:
                result.raw_html = response.text
                result.detected_technologies = TechDetector.detect(result.raw_html)
                
                # Extract title
                soup = BeautifulSoup(result.raw_html, "lxml")
                if soup.title and soup.title.string:
                    result.page_title = soup.title.string.strip()
            else:
                result.error = f"HTTP {response.status_code}"
                
        except httpx.TooManyRedirects:
            result.error = "Redirect loop detected"
        except httpx.ConnectTimeout:
            result.error = "Connection timeout"
        except httpx.RequestError as e:
            result.error = f"Request error: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error in StaticRenderer for {url}: {e}", exc_info=True)
            result.error = f"Unexpected error: {str(e)}"
            
        result.render_duration_ms = int((time.time() - start_time) * 1000)
        return result

    async def close(self):
        await self.client.aclose()
