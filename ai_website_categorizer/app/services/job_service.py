from uuid import UUID
from datetime import datetime
from typing import Dict, Any
from app.models.job import JobStatus
from app.repositories.job_repository import JobRepository
from app.core.exceptions import AppBaseException
from app.core.logger import logger, LoggingContext

class JobStateException(AppBaseException):
    def __init__(self, current_state: JobStatus, target_state: JobStatus, job_id: UUID):
        msg = f"Invalid job state transition from {current_state.value} to {target_state.value} for job {job_id}"
        super().__init__(msg, context={"job_id": str(job_id), "current": current_state.value, "target": target_state.value})

class JobService:
    VALID_TRANSITIONS: Dict[JobStatus, set[JobStatus]] = {
        JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.FAILED},
        JobStatus.RUNNING: {JobStatus.PAUSED, JobStatus.COMPLETED, JobStatus.FAILED},
        JobStatus.PAUSED: {JobStatus.RUNNING, JobStatus.FAILED},
        JobStatus.COMPLETED: set(),
        JobStatus.FAILED: set()
    }

    def __init__(self, repository: JobRepository):
        self.repository = repository

    async def change_status(self, job_id: UUID, new_status: JobStatus) -> None:
        with LoggingContext(job_id=str(job_id), phase="JobStateTransition"):
            job = await self.repository.get_by_id(job_id)
            if not job:
                raise AppBaseException(f"Job {job_id} not found")

            if new_status not in self.VALID_TRANSITIONS.get(job.status, set()):
                raise JobStateException(job.status, new_status, job_id)
            
            job.status = new_status
            if new_status == JobStatus.RUNNING and not job.started_at:
                job.started_at = datetime.utcnow()
            elif new_status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                job.completed_at = datetime.utcnow()
            
            await self.repository.update_status(job_id, new_status)
            logger.info(f"Job transitioned to {new_status.value}")
