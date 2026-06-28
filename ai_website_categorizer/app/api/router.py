import time
import uuid
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.api.v1 import health, crawl, jobs, categories, pages
from app.core.exceptions import AppBaseException
from app.core.logger import logger, request_id_var

# Request ID Middleware
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Generate or use incoming request ID
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(req_id)
        
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_var.reset(token)

# Instantiate the FastAPI App
app = FastAPI(
    title="AI Website Categorization Platform API",
    description="Enterprise-grade website crawler and categorization engine.",
    version="1.0.0"
)

# Add Request ID Middleware
app.add_middleware(RequestIDMiddleware)

# Include API V1 Routers
app.include_router(health.router, prefix="/api/v1")
app.include_router(crawl.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(categories.router, prefix="/api/v1")
app.include_router(pages.router, prefix="/api/v1")

import os
from fastapi.responses import FileResponse

@app.get("/", include_in_schema=False)
async def read_index():
    static_file = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if os.path.exists(static_file):
        return FileResponse(static_file)
    return JSONResponse(status_code=404, content={"message": "UI dashboard file index.html not found."})

# Central Exception Handler mapping AppBaseExceptions and general exceptions
@app.exception_handler(AppBaseException)
async def app_base_exception_handler(request: Request, exc: AppBaseException):
    error_code = exc.__class__.__name__
    req_id = request_id_var.get() or "unknown"
    
    # Map specific exceptions to HTTP statuses
    from app.core.exceptions import BudgetExceededException, RateLimitException, RobotsDeniedException
    
    status_code = 500
    if isinstance(exc, BudgetExceededException):
        status_code = 402  # Payment Required
    elif isinstance(exc, RateLimitException):
        status_code = 429  # Too Many Requests
    elif isinstance(exc, RobotsDeniedException):
        status_code = 403  # Forbidden
    else:
        status_code = 400  # Bad Request

    logger.error(
        f"API handled exception: {exc.message}",
        error_code=error_code,
        status_code=status_code,
        context=exc.context,
        exc_info=True
    )
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": exc.message,
            "context": exc.context,
            "request_id": req_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    req_id = request_id_var.get() or "unknown"
    logger.error("Unhandled API exception", error=str(exc), exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected internal server error occurred.",
            "context": {},
            "request_id": req_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )
