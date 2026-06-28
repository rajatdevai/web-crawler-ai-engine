from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

class ErrorResponse(BaseModel):
    error_code: str = Field(..., description="Machine-readable error identifier")
    message: str = Field(..., description="Human-readable error description")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional debug details")
    request_id: str = Field(..., description="UUID tracing request ID")
    timestamp: str = Field(..., description="ISO-8601 format error timestamp")

class CrawlRequest(BaseModel):
    url: HttpUrl = Field(..., description="The seed URL to start crawling from")
    max_pages: Optional[int] = Field(None, description="Override maximum crawled pages limit")
    max_depth: Optional[int] = Field(None, description="Override maximum crawl depth")
    respect_robots_txt: Optional[bool] = Field(None, description="Override respect robots.txt setting")
    custom_categories: Optional[List[str]] = Field(None, description="Optional custom category signals list")
    crawl_delay: Optional[float] = Field(None, description="Override crawl delay (seconds)")
    allowed_path_prefix: Optional[str] = Field(None, description="Restrict crawling to pages matching this path prefix (e.g. /private-label)")

    @field_validator("url")
    @classmethod
    def validate_http_scheme(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme not in ("http", "https"):
            raise ValueError("URL scheme must be http or https")
        return v

class CrawlAcceptedResponse(BaseModel):
    job_id: UUID
    status: str
    estimated_start_time: datetime
