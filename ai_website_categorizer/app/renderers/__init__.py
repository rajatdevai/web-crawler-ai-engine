from bs4 import BeautifulSoup
from app.renderers.base import RenderResult
from app.renderers.static import StaticRenderer
from app.renderers.playwright_renderer import PlaywrightRenderer
from app.core.logger import logger

class RendererFactory:
    def __init__(self):
        self.static_renderer = StaticRenderer()
        # Initialize lazily to save memory if SPA never encountered
        self.playwright_renderer = None 

    async def render_adaptive(self, url: str) -> RenderResult:
        """
        Executes the Adaptive Rendering Pipeline:
        1. Lightweight HTTP fetch.
        2. Detects dynamic signals.
        3. Escalates to Playwright if needed.
        """
        # Step 1: Static Fetch
        result = await self.static_renderer.render(url)
        
        # If static fetch completely failed (e.g., DNS, Timeout), don't bother with Playwright
        if result.error and "HTTP" not in result.error:
            return result
            
        # Step 2: Dynamic Detection
        if self._needs_dynamic_render(result):
            logger.info(f"Dynamic content detected for {url}, escalating to Playwright.")
            if not self.playwright_renderer:
                self.playwright_renderer = PlaywrightRenderer()
                
            # Step 3: Playwright Fetch
            pw_result = await self.playwright_renderer.render(url)
            
            # If Playwright fails, fallback to whatever we got from static (even if incomplete)
            if pw_result.error:
                logger.warning(f"Playwright failed for {url}, falling back to static result. Error: {pw_result.error}")
                result.error = f"Dynamic render failed: {pw_result.error}"
                return result
                
            return pw_result

        return result

    def _needs_dynamic_render(self, result: RenderResult) -> bool:
        """Determines if Playwright is required based on static HTML."""
        if result.error: 
            return False # E.g., HTTP 404, don't run Playwright
            
        if not result.raw_html:
            return True
            
        soup = BeautifulSoup(result.raw_html, "lxml")
        
        # 1. Content size check
        text = soup.get_text(strip=True)
        if len(text) < 200:
            return True
            
        # 2. Tech check (React, Vue, etc.)
        if any(tech in result.detected_technologies for tech in ["React", "Vue", "Next.js", "Nuxt", "Angular"]):
            # For SSR frameworks like Next.js, content might be large enough natively, 
            # but sometimes we want JS to hydrate. However, if length > 200, we might be fine statically.
            # As per requirements: "The page appears to be React/Next.js/Vue/Angular" -> launch playwright.
            return True
            
        # 3. SPA Root check
        for div_id in ["root", "app"]:
            div = soup.find("div", id=div_id)
            if div and not div.find_all(recursive=False):
                return True

        return False

    async def close(self):
        await self.static_renderer.close()
        if self.playwright_renderer:
            await self.playwright_renderer.close()
