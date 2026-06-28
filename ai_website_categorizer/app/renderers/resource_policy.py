from enum import Enum
import re
from playwright.async_api import Route

class ResourcePolicyMode(str, Enum):
    TEXT_ONLY = "TEXT_ONLY"
    HYBRID = "HYBRID"
    VISION = "VISION"

class ResourcePolicy:
    def __init__(self, mode: ResourcePolicyMode = ResourcePolicyMode.TEXT_ONLY):
        self.mode = mode
        
        self.AD_DOMAINS = [
            "doubleclick.net", "googlesyndication.com", "adsystem.com",
            "facebook.com/tr", "hotjar.com", "clarity.ms", "segment.com", "mixpanel.com"
        ]

    async def apply(self, route: Route):
        """Interception handler for Playwright routes."""
        request = route.request
        resource_type = request.resource_type
        url = request.url.lower()

        # Always block ads and tracking regardless of mode (unless strict vision overrides, but for now block)
        if any(domain in url for domain in self.AD_DOMAINS):
            await route.abort()
            return

        if self.mode == ResourcePolicyMode.VISION:
            # Allow everything else
            await route.continue_()
            return
            
        if self.mode == ResourcePolicyMode.TEXT_ONLY:
            # Block images, fonts, media
            if resource_type in ["image", "media", "font"]:
                await route.abort()
                return
            await route.continue_()
            return
            
        if self.mode == ResourcePolicyMode.HYBRID:
            # Allow hero images (heuristic: large banners, logos, or explicitly early images)
            # For simplicity in Hybrid mode, we might allow images but block media and fonts.
            if resource_type in ["media", "font"]:
                await route.abort()
                return
            await route.continue_()
            return

        # Fallback
        await route.continue_()
