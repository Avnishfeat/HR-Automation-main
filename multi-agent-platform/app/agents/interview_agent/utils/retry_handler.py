
import time
import random
import functools
import logging
import asyncio
import inspect
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)

# [FIX] Added this class to satisfy the ImportError
class RetryConfig:
    """Configuration object for retry logic."""
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, backoff_factor: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.backoff_factor = backoff_factor

def retry_on_failure(
    operation_name: str = "Operation", 
    max_retries: int = 3, 
    base_delay: float = 1.0, 
    backoff_factor: float = 2.0
):
    """
    Decorator to retry a function upon failure with exponential backoff.
    Supports both Sync and Async functions.
    """
    def decorator(func: Callable[..., Any]):
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            delay = base_delay
            last_exception = None
            
            for attempt in range(1, max_retries + 2):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Check retryable flag if present (default True)
                    if not getattr(e, 'retryable', True):
                        raise e

                    last_exception = e
                    if attempt > max_retries:
                        break
                    
                    sleep_time = delay * (1 + random.random() * 0.1)
                    logger.warning(f"{operation_name} failed (Attempt {attempt}/{max_retries}). Retrying in {sleep_time:.2f}s...")
                    await asyncio.sleep(sleep_time)
                    delay *= backoff_factor
            
            if last_exception:
                raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            delay = base_delay
            last_exception = None
            
            for attempt in range(1, max_retries + 2):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if not getattr(e, 'retryable', True):
                        raise e

                    last_exception = e
                    if attempt > max_retries:
                        break
                    
                    sleep_time = delay * (1 + random.random() * 0.1)
                    logger.warning(f"{operation_name} failed (Attempt {attempt}/{max_retries}). Retrying in {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                    delay *= backoff_factor
            
            if last_exception:
                raise last_exception

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
            
    return decorator
