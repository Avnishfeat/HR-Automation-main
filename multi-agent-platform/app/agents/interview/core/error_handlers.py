# app/core/error_handlers.py
"""
Global error handlers for FastAPI application.
Provides structured error responses and logging.
"""
import os
import logging
import traceback
from typing import Dict, Any, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import InterviewBotException

logger = logging.getLogger(__name__)


def create_error_response(
    error_code: str,
    message: str,
    status_code: int,
    details: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a standardized error response."""
    response = {
        "error": {
            "code": error_code,
            "message": message,
            "status_code": status_code
        }
    }
    
    if details:
        response["error"]["details"] = details
    
    if request_id:
        response["error"]["request_id"] = request_id
    
    return response


async def interview_bot_exception_handler(
    request: Request,
    exc: InterviewBotException
) -> JSONResponse:
    """Handle custom InterviewBotException."""
    logger.error(
        f"InterviewBotException: {exc.error_code} - {exc.message}",
        extra={
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "details": exc.details,
            "recoverable": exc.recoverable,
            "path": request.url.path,
            "method": request.method
        },
        exc_info=True
    )
    
    response = create_error_response(
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        request_id=getattr(request.state, "request_id", None)
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors."""
    errors = exc.errors()
    error_messages = []
    
    for error in errors:
        field = ".".join(str(loc) for loc in error["loc"])
        error_messages.append(f"{field}: {error['msg']}")
    
    message = "Validation failed: " + "; ".join(error_messages)
    
    logger.warning(
        f"Validation error: {message}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "errors": errors
        }
    )
    
    response = create_error_response(
        error_code="VALIDATION_ERROR",
        message=message,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details={
            "validation_errors": errors,
            "fields": [{"field": ".".join(str(loc) for loc in e["loc"]), "message": e["msg"]} for e in errors]
        },
        request_id=getattr(request.state, "request_id", None)
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException
) -> JSONResponse:
    """Handle HTTP exceptions."""
    logger.warning(
        f"HTTPException: {exc.status_code} - {exc.detail}",
        extra={
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    # Extract detail if it's a dict
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
        error_code = detail.get("error_code", "HTTP_ERROR")
        error_details = {k: v for k, v in detail.items() if k not in ["message", "error_code"]}
    else:
        message = str(detail)
        error_code = "HTTP_ERROR"
        error_details = {}
    
    response = create_error_response(
        error_code=error_code,
        message=message,
        status_code=exc.status_code,
        details=error_details if error_details else None,
        request_id=getattr(request.state, "request_id", None)
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response
    )


async def general_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """Handle all other unhandled exceptions."""
    error_traceback = traceback.format_exc()
    
    logger.critical(
        f"Unhandled exception: {type(exc).__name__} - {str(exc)}",
        extra={
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "path": request.url.path,
            "method": request.method,
            "traceback": error_traceback
        },
        exc_info=True
    )
    
    # Don't expose internal error details in production
    is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"
    
    if is_production:
        message = "An internal server error occurred. Please try again later."
        details = None
    else:
        message = f"Unhandled exception: {type(exc).__name__}: {str(exc)}"
        details = {"traceback": error_traceback}
    
    response = create_error_response(
        error_code="INTERNAL_SERVER_ERROR",
        message=message,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details=details,
        request_id=getattr(request.state, "request_id", None)
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response
    )


def register_error_handlers(app):
    """Register all error handlers with the FastAPI app."""
    from app.core.exceptions import InterviewBotException
    
    app.add_exception_handler(InterviewBotException, interview_bot_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    logger.info(" Error handlers registered successfully")

