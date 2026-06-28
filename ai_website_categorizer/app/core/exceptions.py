from typing import Optional

class AppBaseException(Exception):
    def __init__(self, message: str, context: Optional[dict] = None, recoverable: bool = False):
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.recoverable = recoverable

class CrawlException(AppBaseException):
    pass

class RenderingException(CrawlException):
    pass

class ExtractionException(AppBaseException):
    pass

class EmbeddingException(AppBaseException):
    pass

class ClassificationException(AppBaseException):
    pass

class DatabaseException(AppBaseException):
    pass

class QueueException(AppBaseException):
    pass

class RateLimitException(CrawlException):
    pass

class RobotsDeniedException(CrawlException):
    pass

class BudgetExceededException(AppBaseException):
    pass
