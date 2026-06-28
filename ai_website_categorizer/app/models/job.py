import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.models import Base
import enum

class JobStatus(enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String, nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING)
    total_pages_discovered = Column(Integer, default=0)
    total_pages_crawled = Column(Integer, default=0)
    total_pages_failed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    config = Column(JSON, nullable=True)
    error_summary = Column(JSON, nullable=True)
