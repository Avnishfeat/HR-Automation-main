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
from app.core.config import settings

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
MAX_CONCURRENT_SESSIONS = settings.MAX_CONCURRENT_INTERVIEWS


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
# CONCURRENCY LIMITER (MongoDB-backed, Async)
# =============================================================================

class ConcurrencyLimiter:
    """
    Limits the number of concurrent active sessions using MongoDB.
    Async implementation for Motor.
    """
    
    def __init__(self, db_handler, max_sessions: int = MAX_CONCURRENT_SESSIONS):
        # db_handler here is expected to be MongoSessionRepository or DatabaseService
        # We'll assume it's MongoSessionRepository and access its db
        self.db_handler = db_handler
        self.max_sessions = max_sessions
        self._collection_name = "active_sessions_counter"
        
        # If db_handler is MongoSessionRepository, it has .db attribute
        if hasattr(db_handler, 'db'):
            self.collection = db_handler.db[self._collection_name]
        else:
            # Fallback or error
            self.collection = None
    
    async def try_acquire(self, session_id: str) -> bool:
        """
        Try to acquire a concurrency slot for a new session.
        """
        if self.collection is None:
            logger.warning("ConcurrencyLimiter: No database connection, allowing request")
            return True  # Fail open
        
        try:
            # Count active sessions
            active_count = await self.collection.count_documents({
                "status": "active",
                "started_at": {"$gte": datetime.utcnow() - timedelta(hours=2)}  # Ignore stale
            })
            
            if active_count >= self.max_sessions:
                logger.warning(
                    f"ConcurrencyLimiter: At capacity ({active_count}/{self.max_sessions})"
                )
                return False
            
            # Register this session
            await self.collection.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "session_id": session_id,
                        "status": "active",
                        "started_at": datetime.utcnow(),
                        "last_heartbeat": datetime.utcnow()
                    }
                },
                upsert=True
            )
            
            logger.info(f"ConcurrencyLimiter: Acquired slot for {session_id} ({active_count + 1}/{self.max_sessions})")
            return True
            
        except Exception as e:
            logger.error(f"ConcurrencyLimiter: Error acquiring slot: {e}")
            return True  # Fail open on error
    
    async def release(self, session_id: str) -> None:
        """Release a concurrency slot when session ends."""
        if self.collection is None:
            return
        
        try:
            await self.collection.update_one(
                {"session_id": session_id},
                {"$set": {"status": "ended", "ended_at": datetime.utcnow()}}
            )
            logger.info(f"ConcurrencyLimiter: Released slot for {session_id}")
        except Exception as e:
            logger.error(f"ConcurrencyLimiter: Error releasing slot: {e}")
    
    async def heartbeat(self, session_id: str) -> None:
        """Update heartbeat timestamp for a session."""
        if self.collection is None:
            return
        
        try:
            await self.collection.update_one(
                {"session_id": session_id},
                {"$set": {"last_heartbeat": datetime.utcnow()}}
            )
        except Exception as e:
            logger.warning(f"ConcurrencyLimiter: Heartbeat failed: {e}")
    
    async def get_active_count(self) -> int:
        """Get current count of active sessions."""
        if self.collection is None:
            return 0
        
        try:
            return await self.collection.count_documents({
                "status": "active",
                "started_at": {"$gte": datetime.utcnow() - timedelta(hours=2)}
            })
        except Exception:
            return 0
    
    async def cleanup_stale(self, max_age_minutes: int = 30) -> int:
        """
        Mark sessions without recent heartbeat as ended.
        """
        if self.collection is None:
            return 0
        
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
            result = await self.collection.update_many(
                {
                    "status": "active",
                    "last_heartbeat": {"$lt": cutoff}
                },
                {"$set": {"status": "zombie_cleaned", "ended_at": datetime.utcnow()}}
            )
            
            if result.modified_count > 0:
                logger.info(f"ConcurrencyLimiter: Cleaned up {result.modified_count} zombie sessions")
            
            return result.modified_count
        except Exception as e:
            logger.error(f"ConcurrencyLimiter: Cleanup failed: {e}")
            return 0


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

concurrency_limiter: Optional[ConcurrencyLimiter] = None


def init_concurrency_limiter(db_handler, max_sessions: int = MAX_CONCURRENT_SESSIONS):
    """Initialize the global concurrency limiter with DB handler."""
    global concurrency_limiter
    concurrency_limiter = ConcurrencyLimiter(db_handler, max_sessions)
    logger.info(f"ConcurrencyLimiter initialized (max_sessions={max_sessions})")
    return concurrency_limiter


def get_concurrency_limiter() -> Optional[ConcurrencyLimiter]:
    """Get the global concurrency limiter instance."""
    return concurrency_limiter
