import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models import Base

class PageEmbedding(Base):
    __tablename__ = "page_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    model = Column(String, nullable=False)
    vector = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    page = relationship("Page")
