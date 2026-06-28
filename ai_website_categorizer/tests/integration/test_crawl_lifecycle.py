import pytest
import json
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from fastapi import status
from app.models.job import JobStatus, CrawlJob
from app.models.page import PageStatus, Page
from app.repositories.job_repository import JobRepository
from app.repositories.page_repository import PageRepository
from app.workers.retry_worker import RetryWorker
from app.workers.embedding_worker import EmbeddingWorker
from app.embeddings.generator import BudgetExceededException

@pytest.mark.asyncio
async def test_api_crawl_post_lifecycle(async_client, mock_redis, test_session):
    # 1. POST /crawl endpoint accepts request and creates job
    response = await async_client.post(
        "/api/v1/crawl",
        json={
            "url": "https://www.makersnutrition.com/",
            "max_pages": 10,
            "max_depth": 2
        }
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "PENDING"

    # Verify job is created in DB
    from uuid import UUID
    job_repo = JobRepository(test_session)
    job = await job_repo.get_by_id(UUID(data["job_id"]))
    assert job is not None
    assert job.status == JobStatus.PENDING
    assert job.url == "https://www.makersnutrition.com/"

    # Verify event pushed to Redis job_start_queue
    event_raw = await mock_redis.pop_from_queue("job_start_queue")
    assert event_raw is not None
    event = json.loads(event_raw)
    assert event["job_id"] == data["job_id"]
    assert event["url"] == "https://www.makersnutrition.com/"

@pytest.mark.asyncio
async def test_page_flow_discovered_to_classified(test_session):
    # Setup job and page
    job = CrawlJob(id=uuid4(), url="https://example.com", status=JobStatus.RUNNING)
    test_session.add(job)
    await test_session.commit()

    page = Page(id=uuid4(), job_id=job.id, url="https://example.com/item", status=PageStatus.DISCOVERED, depth=0)
    test_session.add(page)
    await test_session.commit()

    page_repo = PageRepository(test_session)
    
    # 1. transition to FETCHING
    page.status = PageStatus.FETCHING
    await test_session.commit()
    assert page.status == PageStatus.FETCHING

    # 2. transition to FETCHED
    page.status = PageStatus.FETCHED
    await test_session.commit()
    assert page.status == PageStatus.FETCHED

    # 3. transition to EXTRACTING -> EXTRACTED
    page.status = PageStatus.EXTRACTED
    page.page_document = {"title": "Test Title", "body_text": "Clean body text"}
    await test_session.commit()
    assert page.status == PageStatus.EXTRACTED

    # 4. transition to CLASSIFYING -> CLASSIFIED
    page.status = PageStatus.CLASSIFIED
    page.classification_result = {
        "final_category": "Gummies",
        "final_confidence": 0.95,
        "classification_method": "deterministic"
    }
    await test_session.commit()
    
    # Retrieve page and verify state
    db_page = await page_repo.get_by_id(page.id)
    assert db_page.status == PageStatus.CLASSIFIED
    assert db_page.classification_result["final_category"] == "Gummies"

@pytest.mark.asyncio
async def test_retry_worker_backoff_and_dead_letter(mock_redis, test_session):
    job_id = uuid4()
    page_id = uuid4()
    
    page = Page(id=page_id, job_id=job_id, url="https://example.com/retry-page", status=PageStatus.FAILED, retry_count=0)
    test_session.add(page)
    await test_session.commit()

    # Create retry worker
    worker = RetryWorker(job_id=str(job_id), worker_id="test-retry")
    
    # Mock sleep to run instantly
    import asyncio
    original_sleep = asyncio.sleep
    asyncio.sleep = AsyncMock()

    # Mock DB session in retry worker to use test_session
    from unittest.mock import patch
    with patch("app.workers.retry_worker.get_db_session") as mock_db_ctx:
        # Mock async context manager
        mock_ctx = MagicMock()
        mock_ctx.__aenter__.return_value = test_session
        mock_db_ctx.return_value = mock_ctx

        # 1. Run first retry attempt (retry_count = 1)
        retry_item = {
            "page_id": str(page_id),
            "url": "https://example.com/retry-page",
            "job_id": str(job_id),
            "depth": 0,
            "retry_count": 1
        }
        
        await worker._process_retry(retry_item)
        
        # Verify page status reset to FETCHING
        await test_session.refresh(page)
        assert page.status == PageStatus.FETCHING
        assert page.retry_count == 1
        
        # 2. Run max retries exceeded (retry_count = 4 > max_retries = 3)
        failed_item = {
            "page_id": str(page_id),
            "url": "https://example.com/retry-page",
            "job_id": str(job_id),
            "depth": 0,
            "retry_count": 4
        }
        await worker._process_retry(failed_item)
        
        # Verify routed to dead letter and marked FAILED permanently
        await test_session.refresh(page)
        assert page.status == PageStatus.FAILED
        
        dl_raw = await mock_redis.pop_from_queue("dead_letter_queue")
        assert dl_raw is not None
        dl_item = json.loads(dl_raw)
        assert dl_item["page_id"] == str(page_id)

    asyncio.sleep = original_sleep

@pytest.mark.asyncio
async def test_budget_exceeded_fails_job(mock_redis, test_session):
    job_uuid = uuid4()
    job = CrawlJob(id=job_uuid, url="https://budget.com", status=JobStatus.RUNNING)
    test_session.add(job)
    
    page_uuid = uuid4()
    page = Page(
        id=page_uuid,
        job_id=job_uuid,
        url="https://budget.com/item",
        status=PageStatus.EXTRACTED,
        page_document={"title": "Budget Item", "body_text": "Some text content for embeddings"}
    )
    test_session.add(page)
    await test_session.commit()

    worker = EmbeddingWorker(job_id=str(job_uuid), worker_id="test-budget")
    
    from unittest.mock import patch
    with patch("app.workers.embedding_worker.get_db_session") as mock_db_ctx:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__.return_value = test_session
        mock_db_ctx.return_value = mock_ctx

        # Trigger BudgetExceededException inside batch process
        generator_mock = MagicMock()
        generator_mock.embed_batch = AsyncMock(side_effect=BudgetExceededException(10.0, 5.0, str(job_uuid)))

        batch_items = [{"page_id": str(page_uuid)}]
        await worker._process_batch(batch_items, generator_mock, test_session)

        # Verify job is failed in DB
        await test_session.refresh(job)
        assert job.status == JobStatus.FAILED
        assert job.error_summary["error_code"] == "BUDGET_EXCEEDED"
