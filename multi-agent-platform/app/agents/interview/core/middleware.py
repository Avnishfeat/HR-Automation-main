# app/core/middleware.py
"""
Middleware for request/response processing and error tracking.
"""
import time
import uuid
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Adds a unique request ID to each request for tracking."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Add request ID to response headers
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs request/response information for debugging."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")
        
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None
            }
        )
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Log response
            logger.info(
                f"Response: {request.method} {request.url.path} - {response.status_code}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "process_time": round(process_time, 3)
                }
            )
            
            # Add process time to response headers
            response.headers["X-Process-Time"] = str(round(process_time, 3))
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                    "process_time": round(process_time, 3)
                },
                exc_info=True
            )
            raise


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            
            # Track 5xx errors
            if response.status_code >= 500:
                request_id = getattr(request.state, "request_id", "unknown")
                logger.error(
                    f"Server error in request: {request.method} {request.url.path}",
                    extra={
                        "request_id": request_id,
                        "status_code": response.status_code,
                        "path": request.url.path,
                        "method": request.method
                    }
                )
            
            return response
            
        except Exception as e:
            request_id = getattr(request.state, "request_id", "unknown")
            logger.error(
                f"Unhandled exception in middleware: {type(e).__name__}",
                extra={
                    "request_id": request_id,
                    "exception_type": type(e).__name__,
                    "exception_message": str(e),
                    "path": request.url.path,
                    "method": request.method
                },
                exc_info=True
            )
            raise


def register_middleware(app):
    """Register all middleware with the FastAPI app."""
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(ErrorTrackingMiddleware)
    
    logger.info(" Middleware registered successfully")

