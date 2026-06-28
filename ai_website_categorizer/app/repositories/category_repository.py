from uuid import UUID
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from app.models.category import Category

class CategoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, category: Category) -> Category:
        self.session.add(category)
        await self.session.flush()
        return category

    async def get_by_name(self, job_id: UUID, name: str) -> Optional[Category]:
        stmt = select(Category).where(Category.job_id == job_id, Category.name == name)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_by_job(self, job_id: UUID) -> List[Category]:
        stmt = select(Category).where(Category.job_id == job_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def update_page_count(self, category_id: UUID, increment: int = 1) -> None:
        stmt = update(Category).where(Category.id == category_id).values(
            page_count=Category.page_count + increment
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def bulk_upsert(self, categories: List[dict]) -> None:
        if not categories:
            return
        
        stmt = insert(Category).values(categories)
        stmt = stmt.on_conflict_do_update(
            index_elements=['job_id', 'name'], # Assuming unique constraint
            set_={
                'page_count': stmt.excluded.page_count,
                'avg_confidence': stmt.excluded.avg_confidence
            }
        )
        await self.session.execute(stmt)
        await self.session.flush()
