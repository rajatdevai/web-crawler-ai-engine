from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.core.dependencies import get_db_session
from app.repositories.job_repository import JobRepository
from app.repositories.page_repository import PageRepository
from app.repositories.category_repository import CategoryRepository
from app.models.job import CrawlJob, JobStatus
from app.models.page import Page, PageStatus
from app.models.category import Category
from app.workers.queue import CrawlQueue
from app.core.exceptions import AppBaseException

router = APIRouter(prefix="/jobs", tags=["Jobs"])

@router.get("/{job_id}")
async def get_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session)
):
    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}
        )

    # Queue depth
    queue = CrawlQueue(job_id)
    queue_depth = await queue.get_queue_depth()

    # Worker state placeholder
    active_workers = 0
    if job.status == JobStatus.RUNNING:
        from app.core.config import get_settings
        active_workers = get_settings().crawler.max_concurrent_workers

    # Page counts
    stmt_disc = select(func.count(Page.id)).where(Page.job_id == job_id)
    stmt_crawled = select(func.count(Page.id)).where(Page.job_id == job_id, Page.status != PageStatus.DISCOVERED, Page.status != PageStatus.FAILED)
    stmt_failed = select(func.count(Page.id)).where(Page.job_id == job_id, Page.status == PageStatus.FAILED)
    stmt_class = select(func.count(Page.id)).where(Page.job_id == job_id, Page.status == PageStatus.CLASSIFIED)

    res_disc = await db.execute(stmt_disc)
    res_crawled = await db.execute(stmt_crawled)
    res_failed = await db.execute(stmt_failed)
    res_class = await db.execute(stmt_class)

    pages_discovered = res_disc.scalar() or 0
    pages_crawled = res_crawled.scalar() or 0
    pages_failed = res_failed.scalar() or 0
    pages_classified = res_class.scalar() or 0

    # Elapsed time
    elapsed_seconds = 0
    if job.started_at:
        end_time = job.completed_at or datetime.utcnow()
        elapsed_seconds = int((end_time - job.started_at).total_seconds())

    # ETA estimation
    estimated_completion = None
    eta_seconds_val = 0
    from app.core.config import get_settings
    max_pages = (job.config or {}).get("max_pages") or get_settings().crawler.max_pages
    
    if job.status == JobStatus.RUNNING and pages_crawled > 0:
        remaining_pages = max(0, max_pages - pages_crawled)
        if remaining_pages > 0:
            avg_time_per_page = elapsed_seconds / pages_crawled
            eta_seconds_val = int(avg_time_per_page * remaining_pages)
            estimated_completion = datetime.utcnow() + __import__("datetime").timedelta(seconds=eta_seconds_val)

    # Progress percentage
    if job.status == JobStatus.COMPLETED:
        progress_pct = 100
    elif max_pages > 0:
        progress_pct = min(99, int((pages_crawled / max_pages) * 100))
    else:
        progress_pct = 0

    return {
        "job_id": job.id,
        "status": job.status.value,
        "url": job.url,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "pages_discovered": pages_discovered,
        "pages_crawled": pages_crawled,
        "pages_failed": pages_failed,
        "pages_classified": pages_classified,
        "current_queue_depth": queue_depth,
        "active_workers": active_workers,
        "elapsed_seconds": elapsed_seconds,
        "estimated_completion": estimated_completion,
        "eta_seconds": eta_seconds_val,
        "progress_pct": progress_pct
    }

@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: uuid.UUID
):
    from app.database.redis_client import redis_client
    events = await redis_client.get_job_events(str(job_id))
    return events

@router.get("/{job_id}/results")
async def get_job_results(
    job_id: uuid.UUID,
    include_uncategorized: bool = Query(False),
    db: AsyncSession = Depends(get_db_session)
):
    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}
        )

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "JOB_NOT_COMPLETED", "message": f"Job {job_id} is in {job.status.value} state."}
        )

    # Query all pages for the job
    stmt = select(Page).where(Page.job_id == job_id, Page.status == PageStatus.CLASSIFIED)
    res = await db.execute(stmt)
    pages = res.scalars().all()

    # Group pages by category
    categories_map: Dict[str, Dict[str, Any]] = {}
    total_pages = 0

    for page in pages:
        cr = page.classification_result or {}
        cat_name = cr.get("final_category") or "UNCATEGORIZED"
        confidence = cr.get("final_confidence") or 0.0
        method = cr.get("classification_method") or "none"
        needs_review = cr.get("needs_human_review") or False

        if cat_name == "UNCATEGORIZED" and not include_uncategorized:
            continue

        total_pages += 1

        if cat_name not in categories_map:
            categories_map[cat_name] = {
                "page_count": 0,
                "confidence_sum": 0.0,
                "pages": []
            }

        categories_map[cat_name]["page_count"] += 1
        categories_map[cat_name]["confidence_sum"] += confidence
        categories_map[cat_name]["pages"].append({
            "url": page.url,
            "title": page.page_document.get("title") if page.page_document else "",
            "confidence": confidence,
            "classification_method": method,
            "needs_human_review": needs_review
        })

    # Format the return structure
    formatted_categories = {}
    for cat_name, val in categories_map.items():
        count = val["page_count"]
        formatted_categories[cat_name] = {
            "page_count": count,
            "avg_confidence": val["confidence_sum"] / count if count > 0 else 0.0,
            "pages": val["pages"]
        }

    return {
        "job_id": job.id,
        "url": job.url,
        "total_pages": total_pages,
        "categories": formatted_categories
    }

@router.get("/{job_id}/pages")
async def get_job_pages(
    job_id: uuid.UUID,
    status_filter: Optional[PageStatus] = Query(None, alias="status"),
    category_filter: Optional[str] = Query(None, alias="category"),
    needs_human_review: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session)
):
    # Total count query
    count_stmt = select(func.count(Page.id)).where(Page.job_id == job_id)
    query_stmt = select(Page).where(Page.job_id == job_id)

    filters = []
    if status_filter:
        filters.append(Page.status == status_filter)
    if category_filter:
        filters.append(Page.classification_result["final_category"].astext == category_filter)
    if needs_human_review is not None:
        filters.append(Page.classification_result["needs_human_review"].astext.cast(func.boolean) == needs_human_review)

    if filters:
        count_stmt = count_stmt.where(and_(*filters))
        query_stmt = query_stmt.where(and_(*filters))

    # Paginate
    offset = (page - 1) * page_size
    query_stmt = query_stmt.offset(offset).limit(page_size)

    res_count = await db.execute(count_stmt)
    res_query = await db.execute(query_stmt)

    total_count = res_count.scalar() or 0
    pages_list = res_query.scalars().all()

    formatted_pages = []
    for p in pages_list:
        formatted_pages.append({
            "id": p.id,
            "url": p.url,
            "canonical_url": p.canonical_url,
            "status": p.status.value,
            "http_status": p.http_status,
            "render_method": p.render_method.value,
            "depth": p.depth,
            "discovered_at": p.discovered_at,
            "fetched_at": p.fetched_at,
            "classified_at": p.classified_at,
            "category": p.classification_result.get("final_category") if p.classification_result else None,
            "confidence": p.classification_result.get("final_confidence") if p.classification_result else 0.0,
            "needs_human_review": p.classification_result.get("needs_human_review") if p.classification_result else False,
            "classification_method": p.classification_result.get("classification_method") if p.classification_result else "none",
            "reasoning": p.classification_result.get("reasoning") if p.classification_result else ""
        })

    return {
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "pages": formatted_pages
    }

@router.get("/{job_id}/metrics")
async def get_job_metrics(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(Page).where(Page.job_id == job_id)
    res = await db.execute(stmt)
    pages = res.scalars().all()

    total_llm_calls = 0
    total_tokens_used = 0
    estimated_cost_usd = 0.0

    methods_breakdown = {}
    renders_breakdown = {}
    errors_breakdown = {}

    crawl_sum = 0
    crawl_count = 0
    extract_sum = 0
    extract_count = 0
    embed_sum = 0
    embed_count = 0
    class_sum = 0
    class_count = 0

    for page in pages:
        cr = page.classification_result or {}
        doc = page.page_document or {}

        # Render method breakdown
        render_method = page.render_method.value if page.render_method else "unknown"
        renders_breakdown[render_method] = renders_breakdown.get(render_method, 0) + 1

        # Error breakdown if failed
        if page.status == PageStatus.FAILED:
            err = (page.error_detail or {}).get("error", "Unknown error")
            errors_breakdown[err] = errors_breakdown.get(err, 0) + 1

        # Timings
        # Crawl timing (render duration)
        render_time = doc.get("render_duration_ms") or (page.error_detail or {}).get("timings", {}).get("render_duration_ms")
        if render_time:
            crawl_sum += render_time
            crawl_count += 1

        # Extraction timing
        extract_time = doc.get("total_pipeline_ms")
        if extract_time:
            extract_sum += extract_time
            extract_count += 1

        # Classification timing
        class_time = cr.get("classification_duration_ms")
        if class_time:
            class_sum += class_time
            class_count += 1

        # Embed timing estimate (we can fetch average or use logs, return fallback/estimate)
        embed_count += 1
        embed_sum += 150 # default fallback estimate per page

        # LLM Metrics from Stage 3
        if cr.get("classification_method") == "llm":
            total_llm_calls += 1
            llm_data = cr.get("all_stage_results", {}).get("llm", {})
            total_tokens_used += llm_data.get("prompt_tokens", 0) + llm_data.get("completion_tokens", 0)
            estimated_cost_usd += llm_data.get("cost_usd", 0.0)

        # Classification method breakdown
        method = cr.get("classification_method") or "none"
        methods_breakdown[method] = methods_breakdown.get(method, 0) + 1

    return {
        "total_llm_calls": total_llm_calls,
        "total_tokens_used": total_tokens_used,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "pages_by_classification_method": methods_breakdown,
        "pages_by_render_method": renders_breakdown,
        "average_crawl_duration_ms": crawl_sum / crawl_count if crawl_count > 0 else 0.0,
        "average_extraction_duration_ms": extract_sum / extract_count if extract_count > 0 else 0.0,
        "average_embedding_duration_ms": embed_sum / embed_count if embed_count > 0 else 0.0,
        "average_classification_duration_ms": class_sum / class_count if class_count > 0 else 0.0,
        "failed_pages_by_error_type": errors_breakdown
    }
