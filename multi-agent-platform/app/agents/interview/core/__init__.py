# app/core/__init__.py
"""
Core utilities and error handling for the interview bot.
"""
from app.core.exceptions import (
    InterviewBotException,
    ServiceInitializationError,
    SessionError,
    SessionNotFoundError,
    InterviewExecutionError,
    ExternalServiceError,
    ValidationError,
    DatabaseError,
    MeetConnectionError,
    AnalysisError,
    ResourceNotFoundError
)
from .error_handlers import register_error_handlers
from .middleware import register_middleware
from .retry_handler import retry_on_failure, RetryConfig
from .error_recovery import (
    fallback_on_error,
    safe_execute,
    safe_execute_async,
    CircuitBreaker
)

__all__ = [
    # Exceptions
    "InterviewBotException",
    "ServiceInitializationError",
    "SessionError",
    "SessionNotFoundError",
    "InterviewExecutionError",
    "ExternalServiceError",
    "ValidationError",
    "DatabaseError",
    "MeetConnectionError",
    "AnalysisError",
    "ResourceNotFoundError",
    # Handlers
    "register_error_handlers",
    "register_middleware",
    # Retry
    "retry_on_failure",
    "RetryConfig",
    # Recovery
    "fallback_on_error",
    "safe_execute",
    "safe_execute_async",
    "CircuitBreaker",
]

