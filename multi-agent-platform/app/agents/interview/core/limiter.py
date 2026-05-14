# app/core/limiter.py
"""
Rate Limiting and Concurrency Control

Provides:
1. SlowAPI-based rate limiting with MongoDB storage
2. Custom ConcurrencyLimiter for active session control
"""

import logging
from typing import Optional
from datetime import datetime, timedelta

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Rate limits per endpoint
RATE_LIMITS = {
    "start_interview": "2/minute",      # Heavy resource cost
    "get_status": "60/minute",          # Standard polling
    "end_interview": None,              # Unlimited - never block termination
    "get_snapshots": "30/minute",       # Moderate usage
}

# Maximum concurrent sessions
MAX_CONCURRENT_SESSIONS = 5  # Adjust based on server RAM


# =============================================================================
# IP EXTRACTION (Load Balancer Aware)
# =============================================================================

def get_client_ip(request: Request) -> str:
    """
    Extract client IP, respecting X-Forwarded-For for load balancers.
    Falls back to direct remote address if header not present.
    """
    # Check for X-Forwarded-For header (set by load balancers/proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain (original client)
        return forwarded_for.split(",")[0].strip()

    # Fallback to direct connection IP
    return get_remote_address(request)


# =============================================================================
# RATE LIMITER (SlowAPI)
# =============================================================================

# Create limiter with in-memory storage (MongoDB can be added via limits library)
# Using memory for now as it's simpler and works for single-worker setups
limiter = Limiter(
    key_func=get_client_ip,
    default_limits=["100/minute"],  # Global default
    headers_enabled=True,           # Include Retry-After header
)


# =============================================================================
# CONCURRENCY LIMITER (In-Memory)
# =============================================================================

class ConcurrencyLimiter:
    """
    Limits the number of concurrent active sessions using in-memory dictionary.

    Usage:
        concurrency_limiter = ConcurrencyLimiter(max_sessions=5)

        # In endpoint:
        if not concurrency_limiter.try_acquire(session_id):
            raise HTTPException(503, "Server at capacity")

        # When session ends:
        concurrency_limiter.release(session_id)
    """

    def __init__(self, max_sessions: int = MAX_CONCURRENT_SESSIONS):
        self.max_sessions = max_sessions
        self._active_sessions = {}  # dict mapping session_id -> dict with status, started_at, last_heartbeat

    def try_acquire(self, session_id: str) -> bool:
        """
        Try to acquire a concurrency slot for a new session.

        Returns:
            True if slot acquired, False if at capacity
        """
        try:
            # Clean up stale sessions before checking capacity
            self.cleanup_stale()

            active_count = len(self._active_sessions)

            if active_count >= self.max_sessions:
                logger.warning(
                    f"ConcurrencyLimiter: At capacity ({active_count}/{self.max_sessions})"
                )
                return False

            # Register this session
            self._active_sessions[session_id] = {
                "status": "active",
                "started_at": datetime.utcnow(),
                "last_heartbeat": datetime.utcnow()
            }

            logger.info(f"ConcurrencyLimiter: Acquired slot for {session_id} ({active_count + 1}/{self.max_sessions})")
            return True

        except Exception as e:
            logger.error(f"ConcurrencyLimiter: Error acquiring slot: {e}")
            return True  # Fail open on error

    def release(self, session_id: str) -> None:
        """Release a concurrency slot when session ends."""
        try:
            if session_id in self._active_sessions:
                del self._active_sessions[session_id]
                logger.info(f"ConcurrencyLimiter: Released slot for {session_id}")
        except Exception as e:
            logger.error(f"ConcurrencyLimiter: Error releasing slot: {e}")

    def heartbeat(self, session_id: str) -> None:
        """Update heartbeat timestamp for a session."""
        try:
            if session_id in self._active_sessions:
                self._active_sessions[session_id]["last_heartbeat"] = datetime.utcnow()
        except Exception as e:
            logger.warning(f"ConcurrencyLimiter: Heartbeat failed: {e}")

    def get_active_count(self) -> int:
        """Get current count of active sessions."""
        self.cleanup_stale()
        return len(self._active_sessions)

    def cleanup_stale(self, max_age_minutes: int = 30) -> int:
        """
        Remove sessions without recent heartbeat.
        Returns number of sessions cleaned up.
        """
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
            stale_keys = []
            for sid, data in self._active_sessions.items():
                if data["last_heartbeat"] < cutoff:
                    stale_keys.append(sid)

            for sid in stale_keys:
                del self._active_sessions[sid]

            if stale_keys:
                logger.info(f"ConcurrencyLimiter: Cleaned up {len(stale_keys)} zombie sessions")

            return len(stale_keys)
        except Exception as e:
            logger.error(f"ConcurrencyLimiter: Cleanup failed: {e}")
            return 0


# =============================================================================
# GLOBAL INSTANCE (initialized in startup.py)
# =============================================================================

concurrency_limiter: Optional[ConcurrencyLimiter] = None


def init_concurrency_limiter(max_sessions: int = MAX_CONCURRENT_SESSIONS):
    """Initialize the global concurrency limiter."""
    global concurrency_limiter
    concurrency_limiter = ConcurrencyLimiter(max_sessions)
    logger.info(f"ConcurrencyLimiter initialized (max_sessions={max_sessions})")
    return concurrency_limiter


def get_concurrency_limiter() -> Optional[ConcurrencyLimiter]:
    """Get the global concurrency limiter instance."""
    return concurrency_limiter
