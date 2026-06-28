from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception,
    before_sleep_log
)
import logging
from app.core.config import get_settings
from app.core.exceptions import AppBaseException

logger = logging.getLogger(__name__)
settings = get_settings()

def is_recoverable(exception: BaseException) -> bool:
    if isinstance(exception, AppBaseException):
        return exception.recoverable
    return True # Retry on other unexpected exceptions by default

def with_retry():
    """
    Retry decorator using tenacity.
    Supports exponential backoff with jitter.
    Maximum attempt count is driven by config.
    Only recoverable exceptions trigger retries.
    """
    return retry(
        stop=stop_after_attempt(settings.MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception(is_recoverable),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
