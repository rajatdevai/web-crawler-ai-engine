import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.dependencies import get_db_session
from app.models.category import Category

router = APIRouter(prefix="/categories", tags=["Categories"])

@router.get("")
async def get_categories(
    job_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(Category)
    if job_id:
        stmt = stmt.where(Category.job_id == job_id)
        
    res = await db.execute(stmt)
    categories = res.scalars().all()
    
    return [
        {
            "id": cat.id,
            "job_id": cat.job_id,
            "name": cat.name,
            "description": cat.description,
            "page_count": cat.page_count,
            "avg_confidence": cat.avg_confidence
        }
        for cat in categories
    ]
