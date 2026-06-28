import uuid
from sqlalchemy import Column, Integer, String, Float, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models import Base

class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    page_count = Column(Integer, default=0)
    avg_confidence = Column(Float, default=0.0)
    centroid = Column(JSON, nullable=True)

    job = relationship("CrawlJob")
