from pydantic import BaseModel, HttpUrl, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any
from app.models.job import JobStatus

class JobCreateRequest(BaseModel):
    url: HttpUrl = Field(..., description="The base URL of the website to crawl and categorize", json_schema_extra={"example": "https://www.makersnutrition.com/"})
    max_pages: Optional[int] = Field(None, description="Maximum number of pages to crawl")

class JobResponse(BaseModel):
    id: UUID
    url: HttpUrl
    status: JobStatus
    total_pages_discovered: int
    total_pages_crawled: int
    total_pages_failed: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    
    model_config = {"from_attributes": True}

class JobInternal(JobResponse):
    config: Optional[Dict[str, Any]]
    error_summary: Optional[Dict[str, Any]]
