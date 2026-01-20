# app/core/error_recovery.py
"""
Error recovery utilities for graceful degradation.
"""
import logging
import time
from typing import Callable, Optional, Any, Dict
from functools import wraps

from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


def fallback_on_error(fallback_value: Any = None, fallback_func: Optional[Callable] = None):
    """
    Decorator that provides a fallback value or function when an error occurs.
    
    Args:
        fallback_value: Value to return on error
        fallback_func: Function to call on error (takes same args as decorated function)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"Error in {func.__name__}, using fallback",
                    extra={
                        "function": func.__name__,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                )
                if fallback_func:
                    return await fallback_func(*args, **kwargs)
                return fallback_value
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"Error in {func.__name__}, using fallback",
                    extra={
                        "function": func.__name__,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                )
                if fallback_func:
                    return fallback_func(*args, **kwargs)
                return fallback_value
        
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def safe_execute(func: Callable, default_return: Any = None, log_errors: bool = True) -> Any:
    """
    Safely execute a function, returning a default value on error.
    
    Args:
        func: Function to execute
        default_return: Value to return on error
        log_errors: Whether to log errors
    
    Returns:
        Function result or default_return on error
    """
    try:
        return func()
    except Exception as e:
        if log_errors:
            logger.error(
                f"Error in safe_execute for {func.__name__}: {e}",
                extra={
                    "function": func.__name__,
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
        return default_return


async def safe_execute_async(func: Callable, default_return: Any = None, log_errors: bool = True) -> Any:
    """
    Safely execute an async function, returning a default value on error.
    
    Args:
        func: Async function to execute
        default_return: Value to return on error
        log_errors: Whether to log errors
    
    Returns:
        Function result or default_return on error
    """
    try:
        return await func()
    except Exception as e:
        if log_errors:
            logger.error(
                f"Error in safe_execute_async for {func.__name__}: {e}",
                extra={
                    "function": func.__name__,
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
        return default_return


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for preventing cascading failures.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open
    
    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
                logger.info(f"Circuit breaker for {func.__name__} entering half-open state")
            else:
                raise ExternalServiceError(
                    service_name=func.__name__,
                    operation="circuit_breaker",
                    reason="Circuit breaker is open",
                    retryable=True
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    async def call_async(self, func: Callable, *args, **kwargs):
        """Execute async function with circuit breaker protection."""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
                logger.info(f"Circuit breaker for {func.__name__} entering half-open state")
            else:
                raise ExternalServiceError(
                    service_name=func.__name__,
                    operation="circuit_breaker",
                    reason="Circuit breaker is open",
                    retryable=True
                )
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        if self.state == "half_open":
            self.state = "closed"
            logger.info("Circuit breaker closed after successful call")
    
    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        return (time.time() - self.last_failure_time) >= self.recovery_timeout
    
    def reset(self):
        """Manually reset the circuit breaker."""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"
        logger.info("Circuit breaker manually reset")

