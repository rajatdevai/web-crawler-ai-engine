from uuid import UUID
from datetime import datetime
from typing import Dict
from app.models.page import PageStatus
from app.repositories.page_repository import PageRepository
from app.core.exceptions import AppBaseException
from app.core.logger import logger, LoggingContext
from app.workers.queue import CrawlQueue
from app.core.config import get_settings

class PageStateException(AppBaseException):
    def __init__(self, current_state: PageStatus, target_state: PageStatus, page_id: UUID):
        msg = f"Invalid page state transition from {current_state.value} to {target_state.value} for page {page_id}"
        super().__init__(msg, context={"page_id": str(page_id), "current": current_state.value, "target": target_state.value})

class PageService:
    VALID_TRANSITIONS: Dict[PageStatus, set[PageStatus]] = {
        PageStatus.DISCOVERED: {PageStatus.FETCHING, PageStatus.FAILED},
        PageStatus.FETCHING: {PageStatus.FETCHED, PageStatus.FAILED},
        PageStatus.FETCHED: {PageStatus.EXTRACTING, PageStatus.FAILED},
        PageStatus.EXTRACTING: {PageStatus.EXTRACTED, PageStatus.FAILED},
        PageStatus.EXTRACTED: {PageStatus.CLASSIFYING, PageStatus.FAILED},
        PageStatus.CLASSIFYING: {PageStatus.CLASSIFIED, PageStatus.FAILED},
        PageStatus.CLASSIFIED: set(),
        PageStatus.FAILED: {PageStatus.FETCHING} # Allowed if retrying
    }

    def __init__(self, repository: PageRepository):
        self.repository = repository
        self.settings = get_settings()

    async def change_status(self, page_id: UUID, new_status: PageStatus, error_detail: dict = None) -> None:
        with LoggingContext(page_id=str(page_id), phase="PageStateTransition"):
            page = await self.repository.get_by_id(page_id)
            if not page:
                raise AppBaseException(f"Page {page_id} not found")

            if new_status not in self.VALID_TRANSITIONS.get(page.status, set()):
                raise PageStateException(page.status, new_status, page_id)
            
            page.status = new_status
            
            if new_status == PageStatus.FETCHED:
                page.fetched_at = datetime.utcnow()
            elif new_status == PageStatus.CLASSIFIED:
                page.classified_at = datetime.utcnow()
            elif new_status == PageStatus.FAILED:
                if error_detail:
                    page.error_detail = error_detail
                await self._handle_failure(page)
            
            await self.repository.update_status(page_id, new_status)
            logger.info(f"Page transitioned to {new_status.value}")

    async def _handle_failure(self, page) -> None:
        queue = CrawlQueue(page.job_id)
        queue_item = {
            "page_id": str(page.id),
            "url": page.url,
            "job_id": str(page.job_id),
            "depth": page.depth,
            "retry_count": page.retry_count + 1
        }
        
        if page.retry_count < self.settings.crawler.max_retries:
            page.retry_count += 1
            await queue.push_retry(queue_item)
            logger.warning(f"Page pushed to retry queue. Attempt {page.retry_count}")
        else:
            await queue.push_dead_letter(queue_item)
            logger.error("Page exceeded max retries. Pushed to dead letter queue.")
