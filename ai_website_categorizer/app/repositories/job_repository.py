from uuid import UUID
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.models.job import CrawlJob, JobStatus

class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, job: CrawlJob) -> CrawlJob:
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_by_id(self, job_id: UUID) -> Optional[CrawlJob]:
        stmt = select(CrawlJob).where(CrawlJob.id == job_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def update_status(self, job_id: UUID, status: JobStatus) -> None:
        stmt = update(CrawlJob).where(CrawlJob.id == job_id).values(status=status)
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_metrics(self, job_id: UUID, discovered: int = 0, crawled: int = 0, failed: int = 0) -> None:
        stmt = (
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(
                total_pages_discovered=CrawlJob.total_pages_discovered + discovered,
                total_pages_crawled=CrawlJob.total_pages_crawled + crawled,
                total_pages_failed=CrawlJob.total_pages_failed + failed,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def list_all(self, limit: int = 100, offset: int = 0) -> List[CrawlJob]:
        stmt = select(CrawlJob).limit(limit).offset(offset).order_by(CrawlJob.created_at.desc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def delete(self, job_id: UUID) -> None:
        stmt = delete(CrawlJob).where(CrawlJob.id == job_id)
        await self.session.execute(stmt)
        await self.session.flush()
