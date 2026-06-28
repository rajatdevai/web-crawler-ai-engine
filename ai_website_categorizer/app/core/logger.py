import logging
import sys
import structlog
from contextvars import ContextVar
from typing import Any
from app.core.config import get_settings

job_id_var: ContextVar[str] = ContextVar("job_id", default="")
page_id_var: ContextVar[str] = ContextVar("page_id", default="")
worker_id_var: ContextVar[str] = ContextVar("worker_id", default="")
phase_var: ContextVar[str] = ContextVar("phase", default="")
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

def add_contextvars(logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
    if job_id := job_id_var.get():
        event_dict["job_id"] = job_id
    if page_id := page_id_var.get():
        event_dict["page_id"] = page_id
    if worker_id := worker_id_var.get():
        event_dict["worker_id"] = worker_id
    if phase := phase_var.get():
        event_dict["phase"] = phase
    if request_id := request_id_var.get():
        event_dict["request_id"] = request_id
    return event_dict

def drop_sensitive_data(logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
    sensitive_keys = {"api_key", "password", "vector", "html_content", "raw_html"}
    return {k: v for k, v in event_dict.items() if k not in sensitive_keys}

def setup_logger():
    settings = get_settings()
    
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_contextvars,
        drop_sensitive_data,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.contextvars.merge_contextvars,
    ]

    if settings.app.env == "production":
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO if not settings.app.debug else logging.DEBUG,
    )

    return structlog.get_logger()

logger = setup_logger()

class LoggingContext:
    def __init__(self, job_id: str = "", page_id: str = "", worker_id: str = "", phase: str = ""):
        self.job_id = job_id
        self.page_id = page_id
        self.worker_id = worker_id
        self.phase = phase
        self.tokens = []

    def __enter__(self):
        if self.job_id:
            self.tokens.append((job_id_var, job_id_var.set(self.job_id)))
        if self.page_id:
            self.tokens.append((page_id_var, page_id_var.set(self.page_id)))
        if self.worker_id:
            self.tokens.append((worker_id_var, worker_id_var.set(self.worker_id)))
        if self.phase:
            self.tokens.append((phase_var, phase_var.set(self.phase)))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for var, token in reversed(self.tokens):
            var.reset(token)

def sample_log(logger_instance: Any, rate: int, level: str, message: str, **kwargs):
    """
    Log sampling utility. E.g., rate=100 means log 1 out of 100 events.
    In real scale, we might use a random int or hash, but a counter is simple.
    """
    import random
    if random.randint(1, rate) == 1:
        getattr(logger_instance, level)(message, **kwargs)
