from pydantic import BaseModel, HttpUrl, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any
from app.models.page import PageStatus, RenderMethod

class PageResponse(BaseModel):
    id: UUID
    job_id: UUID
    url: HttpUrl
    canonical_url: Optional[HttpUrl]
    status: PageStatus
    http_status: Optional[int]
    render_method: RenderMethod
    depth: int
    discovered_at: datetime
    fetched_at: Optional[datetime]
    classified_at: Optional[datetime]
    
    model_config = {"from_attributes": True}

class PageInternal(PageResponse):
    retry_count: int
    error_detail: Optional[Dict[str, Any]]
