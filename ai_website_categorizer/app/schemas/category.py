from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional

class CategoryResponse(BaseModel):
    id: UUID
    job_id: UUID
    name: str
    description: Optional[str]
    page_count: int
    avg_confidence: float

    model_config = {"from_attributes": True}
