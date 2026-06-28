import asyncio
import time
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, BrowserContext, TimeoutError as PlaywrightTimeoutError
from app.renderers.base import BaseRenderer, RenderResult
from app.renderers.tech_detection import TechDetector
from app.renderers.resource_policy import ResourcePolicy, ResourcePolicyMode
from app.models.page import RenderMethod
from app.core.config import get_settings
from app.core.logger import logger

class PlaywrightRenderer(BaseRenderer):
    def __init__(self, pool_size: int = 3):
        self.settings = get_settings()
        self.pool_size = pool_size
        self.playwright = None
        self.browser: Browser = None
        self.contexts: asyncio.Queue[BrowserContext] = asyncio.Queue()
        self.policy = ResourcePolicy(mode=ResourcePolicyMode.TEXT_ONLY)
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return
        logger.info("Initializing Playwright browser pool...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.settings.playwright.headless,
            args=['--disable-dev-shm-usage', '--no-sandbox']
        )
        
        for _ in range(self.pool_size):
            context = await self._create_context()
            await self.contexts.put(context)
            
        self.initialized = True
        logger.info(f"Playwright pool initialized with {self.pool_size} contexts.")

    async def _create_context(self) -> BrowserContext:
        context = await self.browser.new_context(
            user_agent=self.settings.crawler.user_agent,
            viewport={"width": 1920, "height": 1080}
        )
        # Apply route interception for resource blocking
        await context.route("**/*", self.policy.apply)
        return context

    async def _recreate_context(self, old_context: BrowserContext) -> BrowserContext:
        try:
            await old_context.close()
        except Exception:
            pass
        return await self._create_context()

    async def render(self, url: str) -> RenderResult:
        if not self.initialized:
            await self.initialize()
            
        start_time = time.time()
        result = RenderResult(render_method=RenderMethod.PLAYWRIGHT)
        
        # Acquire context from pool
        context = await self.contexts.get()
        page = None
        
        try:
            page = await context.new_page()
            
            # Primary strategy: networkidle
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=self.settings.playwright.timeout)
            except PlaywrightTimeoutError:
                logger.warning(f"networkidle timeout for {url}, falling back to domcontentloaded")
                response = await page.goto(url, wait_until="domcontentloaded", timeout=self.settings.playwright.timeout)
                await asyncio.sleep(2) # Adaptive wait
                
            if response:
                result.http_status = response.status
                
            # Scroll to trigger lazy loading
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1) # Settle time
            
            result.raw_html = await page.content()
            result.final_url = page.url
            
            # Verify meaningful content exists
            soup = BeautifulSoup(result.raw_html, "lxml")
            if soup.title and soup.title.string:
                result.page_title = soup.title.string.strip()
                
            result.detected_technologies = TechDetector.detect(result.raw_html)
            
        except Exception as e:
            logger.error(f"Playwright error rendering {url}: {e}")
            result.error = f"Playwright error: {str(e)}"
            # If context is corrupted, recreate it
            context = await self._recreate_context(context)
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            # Release context back to pool
            await self.contexts.put(context)
            
        result.render_duration_ms = int((time.time() - start_time) * 1000)
        return result

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.initialized = False
