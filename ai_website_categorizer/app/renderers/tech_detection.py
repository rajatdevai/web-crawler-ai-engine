from bs4 import BeautifulSoup
from typing import List

class TechDetector:
    @staticmethod
    def detect(html: str) -> List[str]:
        """Scans HTML payload for technology signals."""
        technologies = []
        if not html:
            return technologies
            
        soup = BeautifulSoup(html, "lxml")
        
        # React / Next.js
        if soup.find(id="__NEXT_DATA__") or soup.find("script", id="__NEXT_DATA__"):
            technologies.append("Next.js")
            technologies.append("React")
        elif soup.find(attrs={"data-reactroot": True}):
            technologies.append("React")
            
        # Vue / Nuxt
        if soup.find(id="__NUXT__") or soup.find("script", id="__NUXT__"):
            technologies.append("Nuxt")
            technologies.append("Vue")
        elif soup.find(attrs=lambda x: x and str(x).startswith("data-v-")):
            technologies.append("Vue")
            
        # Angular
        if soup.find(attrs={"ng-version": True}):
            technologies.append("Angular")
            
        # WordPress
        if "wp-content" in html or "wp-includes" in html:
            technologies.append("WordPress")
            
        # Shopify
        if "Shopify.shop" in html or "cdn.shopify.com" in html:
            technologies.append("Shopify")
            
        return list(set(technologies))
