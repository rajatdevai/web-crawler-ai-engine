from datetime import datetime
import json
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db_session
from app.repositories.job_repository import JobRepository
from app.models.job import CrawlJob, JobStatus
from app.schemas.api_responses import CrawlRequest, CrawlAcceptedResponse
from app.database.redis_client import redis_client
from app.core.logger import logger

router = APIRouter(prefix="/crawl", tags=["Crawl"])

@router.post("", response_model=CrawlAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_crawl(
    request: CrawlRequest,
    db: AsyncSession = Depends(get_db_session)
):
    job_id = uuid.uuid4()
    
    # 1. Map config parameters
    job_config = {
        "max_pages": request.max_pages,
        "max_depth": request.max_depth,
        "respect_robots_txt": request.respect_robots_txt if request.respect_robots_txt is not None else True,
        "custom_categories": request.custom_categories,
        "crawl_delay": request.crawl_delay,
        "allowed_path_prefix": request.allowed_path_prefix
    }
    
    # 2. Create the CrawlJob in PENDING state
    job_repo = JobRepository(db)
    job = CrawlJob(
        id=job_id,
        url=str(request.url),
        status=JobStatus.PENDING,
        created_at=datetime.utcnow(),
        config=job_config
    )
    await job_repo.create(job)
    await db.commit()
    
    # 3. Push a job_start event to the worker queue in Redis
    event = {
        "job_id": str(job_id),
        "url": str(request.url),
        "config": job_config
    }
    await redis_client.push_to_queue("job_start_queue", json.dumps(event))
    
    logger.info("Crawl job accepted and queued", job_id=str(job_id), url=str(request.url))
    
    return CrawlAcceptedResponse(
        job_id=job_id,
        status="PENDING",
        estimated_start_time=datetime.utcnow()
    )
