from uuid import UUID
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from app.models.page import Page, PageStatus
from app.utils.hashing import get_url_hash

class PageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, page: Page) -> Page:
        self.session.add(page)
        await self.session.flush()
        return page

    async def get_by_id(self, page_id: UUID) -> Optional[Page]:
        stmt = select(Page).where(Page.id == page_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_by_url_hash(self, url: str) -> Optional[Page]:
        # Using exact URL for simplicity, real impl might use a hash column
        stmt = select(Page).where(Page.url == url)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def update_status(self, page_id: UUID, status: PageStatus) -> None:
        stmt = update(Page).where(Page.id == page_id).values(status=status)
        await self.session.execute(stmt)
        await self.session.flush()

    async def bulk_create(self, pages: List[Page]) -> None:
        self.session.add_all(pages)
        await self.session.flush()

    async def get_pages_by_job(self, job_id: UUID, limit: int = 100, offset: int = 0) -> List[Page]:
        stmt = select(Page).where(Page.job_id == job_id).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_pages_by_category(self, category_id: UUID, limit: int = 100, offset: int = 0) -> List[Page]:
        # For now, assumes category mapping exists. (M2M table might be needed later)
        return []

    async def get_failed_pages(self, job_id: UUID, limit: int = 100) -> List[Page]:
        stmt = select(Page).where(Page.job_id == job_id, Page.status == PageStatus.FAILED).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def count_by_status(self, job_id: UUID, status: PageStatus) -> int:
        stmt = select(func.count(Page.id)).where(Page.job_id == job_id, Page.status == status)
        res = await self.session.execute(stmt)
        return res.scalar() or 0
