# app/core/cleanup.py
"""
Zombie Process Cleanup

Background task that cleans up stale sessions that haven't sent a heartbeat,
releasing their concurrency slots and freeing server resources.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.agents.interview.core.limiter import get_concurrency_limiter

logger = logging.getLogger(__name__)

# Cleanup configuration
CLEANUP_INTERVAL_SECONDS = 300  # Run every 5 minutes
STALE_SESSION_THRESHOLD_MINUTES = 30  # Mark as zombie if no heartbeat for 30 mins


class ZombieCleanupTask:
    """
    Background task that periodically cleans up stale/zombie sessions.
    """
    
    def __init__(self, interval_seconds: int = CLEANUP_INTERVAL_SECONDS):
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the cleanup background task."""
        if self._running:
            logger.warning("ZombieCleanupTask already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"ZombieCleanupTask started (interval: {self.interval}s)")
    
    async def stop(self):
        """Stop the cleanup background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ZombieCleanupTask stopped")
    
    async def _cleanup_loop(self):
        """Main cleanup loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                await self._perform_cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ZombieCleanupTask error: {e}", exc_info=True)
    
    async def _perform_cleanup(self):
        """Perform the actual cleanup of stale sessions."""
        concurrency_limiter = get_concurrency_limiter()
        if not concurrency_limiter:
            return
        
        try:
            cleaned = concurrency_limiter.cleanup_stale(
                max_age_minutes=STALE_SESSION_THRESHOLD_MINUTES
            )
            
            if cleaned > 0:
                logger.info(
                    f"ZombieCleanup: Released {cleaned} stale session slots "
                    f"(inactive > {STALE_SESSION_THRESHOLD_MINUTES} mins)"
                )
        except Exception as e:
            logger.error(f"ZombieCleanup failed: {e}")


# Global instance
_cleanup_task: Optional[ZombieCleanupTask] = None


def get_cleanup_task() -> Optional[ZombieCleanupTask]:
    """Get the global cleanup task instance."""
    return _cleanup_task


async def start_cleanup_task():
    """Initialize and start the zombie cleanup background task."""
    global _cleanup_task
    _cleanup_task = ZombieCleanupTask()
    await _cleanup_task.start()
    return _cleanup_task


async def stop_cleanup_task():
    """Stop the zombie cleanup background task."""
    global _cleanup_task
    if _cleanup_task:
        await _cleanup_task.stop()
        _cleanup_task = None
