# app/core/startup.py
import logging
from typing import Optional
from fastapi import FastAPI
import urllib3

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.agents.interview.services.audio.audio_handler import AudioHandler
from app.agents.interview.services.interview_service import InterviewService
from app.agents.interview.services.analysis.transcript_analyzer import TranscriptAnalyzer
from app.agents.interview.services.analysis.combined_analyzer import CombinedAnalyzer
from app.agents.interview.infrastructure.selenium.meet_session_manager import MeetSessionManager
from app.agents.interview.orchestrator.meet_interview_orchestrator import MeetInterviewOrchestrator
from app.agents.interview.services.audio.stt_service import STTService
from app.agents.interview.services.audio.tts_service import TTSService
from app.core.exceptions import ServiceInitializationError
from app.agents.interview.core.error_handlers import register_error_handlers
from app.agents.interview.core.middleware import register_middleware
from app.agents.interview.core.limiter import limiter, init_concurrency_limiter
from app.agents.interview.core.cleanup import start_cleanup_task, stop_cleanup_task

logger = logging.getLogger(__name__)

class ServiceContainer:
    """Container for all application services"""
    
    interview_service: Optional[InterviewService] = None
    transcript_analyzer: Optional[TranscriptAnalyzer] = None
    meet_session_mgr: Optional[MeetSessionManager] = None
    meet_orchestrator: Optional[MeetInterviewOrchestrator] = None
    combined_analyzer: Optional[CombinedAnalyzer] = None
    stt_service: Optional[STTService] = None
    tts_service: Optional[TTSService] = None

services = ServiceContainer()

def initialize_services():
    try:
        # FIX 1: Increase urllib3 connection pool size BEFORE initializing services
        urllib3.PoolManager(num_pools=50, maxsize=100)
        logger.info(" urllib3 connection pool configured (maxsize=100)")
        
        # Initialize concurrency limiter
        init_concurrency_limiter(max_sessions=5)
        
        # 2. Analysis Services
        try:
            services.transcript_analyzer = TranscriptAnalyzer()
            services.combined_analyzer = CombinedAnalyzer()
            logger.info("Analysis services initialized (Singleton)")
        except Exception as e:
            raise ServiceInitializationError("Analysis Services", str(e))
            
        # 3. Session & Audio Managers
        try:
            services.meet_session_mgr = MeetSessionManager()
            services.audio_handler = AudioHandler()
            services.stt_service = STTService(services.meet_session_mgr)
            
            logger.info("Session & Audio managers initialized")
        except Exception as e:
            raise ServiceInitializationError("Session/Audio Managers", str(e))
        
        # 4. Core Logic Services
        try:
            services.interview_service = InterviewService(
                combined_analyzer=services.combined_analyzer 
            )
            logger.info("Core Interview Service initialized (with injected Analyzer)")
        except Exception as e:
            raise ServiceInitializationError("Core Services", str(e))
        
        # 5. Audio Output (TTS)
        try:
            services.tts_service = TTSService()
            logger.info("TTS service initialized")
        except Exception as e:
            raise ServiceInitializationError("Audio Services", str(e))

        # 6. Orchestration
        try:
            services.meet_orchestrator = MeetInterviewOrchestrator(
                services.meet_session_mgr, 
                services.interview_service,
                stt_service=services.stt_service,
                audio_handler=services.audio_handler
            )
            logger.info("Orchestration services initialized")
        except Exception as e:
            raise ServiceInitializationError("Orchestration Services", str(e))

        logger.info(" All services initialized successfully (Singleton Pattern Enforced)")
        
    except ServiceInitializationError:
        raise
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to initialize services: {e}", exc_info=True)
        raise ServiceInitializationError("Unknown Service", str(e))

def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Interviewer API",
        description="Conducts interviews and provides combined analysis."
    )
    
    # Register rate limit exception handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    register_error_handlers(app)
    register_middleware(app)
    initialize_services()
    
    from app.agents.interview.api import interview, health
    from app.agents.interview.services.gemini_service import GeminiService

    app.include_router(interview.router, prefix="/interview", tags=["Interview"])
    app.include_router(health.router, tags=["Health"])
    
    @app.get("/")
    def read_root():
        return {"status": "AI Interviewer API is running"}
    
    # Register startup event for cleanup task
    @app.on_event("startup")
    async def startup_event():
        """Start background cleanup task on app startup"""
        await start_cleanup_task()
        logger.info(" Zombie cleanup task started")
    
    # Add shutdown handler to gracefully close HTTP connections
    @app.on_event("shutdown")
    async def shutdown_event():
        """Cleanup connections on application shutdown"""
        logger.info("Shutting down application...")
        await stop_cleanup_task()
        GeminiService.cleanup_shared_client()
        logger.info(" Application shutdown complete")
    
    return app

def get_services() -> ServiceContainer:
    return services