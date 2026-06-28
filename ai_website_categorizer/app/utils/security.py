import re
import tldextract
from bs4 import BeautifulSoup
from fastapi import Request, HTTPException, status
from app.core.logger import logger
from app.core.config import get_settings

class URLSanitizer:
    @staticmethod
    def sanitize(url: str) -> str:
        """Strips dangerous schemas from URL."""
        lower_url = url.lower().strip()
        if lower_url.startswith("javascript:") or lower_url.startswith("data:"):
            logger.warning(f"Blocked dangerous URL schema: {url}")
            return ""
        return url
        
    @staticmethod
    def get_normalized_domain(url: str) -> str:
        """Extracts registrable domain (e.g. blog.amazon.co.uk -> amazon.co.uk)"""
        ext = tldextract.extract(url)
        return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain

class ContentSanitizer:
    @staticmethod
    def sanitize(html_content: str) -> str:
        """Strips script tags and event handlers from HTML."""
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "lxml")
        
        # Remove script and style tags completely
        for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
            tag.decompose()
            
        # Remove javascript event handlers (e.g., onclick, onload)
        for tag in soup.find_all(True):
            attrs_to_remove = [attr for attr in tag.attrs if attr.lower().startswith('on')]
            for attr in attrs_to_remove:
                del tag[attr]
                
        return str(soup)

class PromptInjectionDetector:
    # Common signatures for prompt overrides
    INJECTION_SIGNATURES = [
        re.compile(r"ignore\s+all\s+previous\s+instructions", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
        re.compile(r"system\s+prompt", re.IGNORECASE),
        re.compile(r"override\s+instructions", re.IGNORECASE)
    ]
    
    @staticmethod
    def is_injected(text: str) -> bool:
        """Scans extracted page text for patterns that attempt to override AI instructions."""
        for pattern in PromptInjectionDetector.INJECTION_SIGNATURES:
            if pattern.search(text):
                logger.warning("Prompt injection pattern detected in content")
                return True
        return False

class PayloadSizeLimiter:
    def __init__(self):
        self.settings = get_settings()
        self.max_bytes = self.settings.security.max_payload_size_mb * 1024 * 1024
        
    async def __call__(self, request: Request):
        content_length = request.headers.get("content-length")
        if content_length:
            if int(content_length) > self.max_bytes:
                logger.error(f"Payload too large: {content_length} bytes > {self.max_bytes} bytes")
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Payload Too Large. Maximum allowed is {self.settings.security.max_payload_size_mb} MB."
                )
        return True
