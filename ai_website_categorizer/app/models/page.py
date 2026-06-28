import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.models import Base
import enum

# Use JSONB on PostgreSQL and JSON on SQLite for cross-platform test compatibility
JSONB_type = JSON().with_variant(JSONB, "postgresql")

class PageStatus(enum.Enum):
    DISCOVERED = "DISCOVERED"
    FETCHING = "FETCHING"
    FETCHED = "FETCHED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    CLASSIFYING = "CLASSIFYING"
    CLASSIFIED = "CLASSIFIED"
    FAILED = "FAILED"

class RenderMethod(enum.Enum):
    STATIC = "STATIC"
    PLAYWRIGHT = "PLAYWRIGHT"

class Page(Base):
    __tablename__ = "pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=False, index=True)
    canonical_url = Column(String, nullable=True)
    status = Column(Enum(PageStatus), default=PageStatus.DISCOVERED)
    http_status = Column(Integer, nullable=True)
    render_method = Column(Enum(RenderMethod), default=RenderMethod.STATIC)
    depth = Column(Integer, default=0)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    fetched_at = Column(DateTime, nullable=True)
    classified_at = Column(DateTime, nullable=True)
    extracted_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    error_detail = Column(JSON, nullable=True)
    extracted_content = Column(JSONB_type, nullable=True)  # kept for migration compat — aliased by page_document
    page_document = Column(JSONB_type, nullable=True)       # canonical PageDocument — source of truth for all AI services
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 for duplicate content detection
    
    # Classification columns
    classification_result = Column(JSONB_type, nullable=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)

    job = relationship("CrawlJob")
    category = relationship("Category")
