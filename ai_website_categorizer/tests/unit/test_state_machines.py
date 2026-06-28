import pytest
from uuid import uuid4
from app.models.job import JobStatus, CrawlJob
from app.models.page import PageStatus, Page
from app.services.job_service import JobService, JobStateException
from app.services.page_service import PageService, PageStateException
from app.core.exceptions import AppBaseException

class MockRepository:
    def __init__(self, record):
        self.record = record
        self.updated_status = None

    async def get_by_id(self, record_id):
        return self.record

    async def update_status(self, record_id, status):
        self.updated_status = status
        self.record.status = status

def test_job_state_machine_valid():
    job = CrawlJob(id=uuid4(), status=JobStatus.PENDING)
    repo = MockRepository(job)
    service = JobService(repo)
    
    # Run loop through standard transitions
    import asyncio
    # PENDING -> RUNNING
    asyncio.run(service.change_status(job.id, JobStatus.RUNNING))
    assert job.status == JobStatus.RUNNING
    
    # RUNNING -> COMPLETED
    asyncio.run(service.change_status(job.id, JobStatus.COMPLETED))
    assert job.status == JobStatus.COMPLETED

def test_job_state_machine_invalid():
    job = CrawlJob(id=uuid4(), status=JobStatus.PENDING)
    repo = MockRepository(job)
    service = JobService(repo)
    
    import asyncio
    # PENDING -> COMPLETED is invalid (must go through RUNNING)
    with pytest.raises(JobStateException):
        asyncio.run(service.change_status(job.id, JobStatus.COMPLETED))

def test_page_state_machine_valid():
    page = Page(id=uuid4(), status=PageStatus.DISCOVERED, retry_count=0)
    repo = MockRepository(page)
    service = PageService(repo)
    
    import asyncio
    # DISCOVERED -> FETCHING
    asyncio.run(service.change_status(page.id, PageStatus.FETCHING))
    assert page.status == PageStatus.FETCHING
    
    # FETCHING -> FETCHED
    asyncio.run(service.change_status(page.id, PageStatus.FETCHED))
    assert page.status == PageStatus.FETCHED

def test_page_state_machine_invalid():
    page = Page(id=uuid4(), status=PageStatus.DISCOVERED, retry_count=0)
    repo = MockRepository(page)
    service = PageService(repo)
    
    import asyncio
    # DISCOVERED -> CLASSIFIED is invalid
    with pytest.raises(PageStateException):
        asyncio.run(service.change_status(page.id, PageStatus.CLASSIFIED))
