
# app/services/interview/service_container.py
import logging
import urllib3
from typing import Optional

from app.agents.interview_agent.mongo_session_repository import MongoSessionRepository
from app.agents.interview_agent.audio.audio_handler import AudioHandler
from app.agents.interview_agent.interview_service import InterviewService
from app.agents.interview_agent.analysis.transcript_parser import TranscriptParser
from app.agents.interview_agent.analysis.transcript_analyzer import TranscriptAnalyzer
from app.agents.interview_agent.analysis.combined_analyzer import CombinedAnalyzer
from app.agents.interview_agent.selenium.meet_session_manager import MeetSessionManager
from app.agents.interview_agent.orchestrator.meet_interview_orchestrator import MeetInterviewOrchestrator
from app.agents.interview_agent.audio.stt_service import STTService
from app.agents.interview_agent.audio.tts_service import TTSService
from app.agents.interview_agent.utils.exceptions import ServiceInitializationError
from app.agents.interview_agent.utils.limiter import init_concurrency_limiter

logger = logging.getLogger(__name__)

class ServiceContainer:
    """Container for all interview application services"""
    db_handler: Optional[MongoSessionRepository] = None 
    
    interview_service: Optional[InterviewService] = None
    transcript_parser: Optional[TranscriptParser] = None
    transcript_analyzer: Optional[TranscriptAnalyzer] = None
    meet_session_mgr: Optional[MeetSessionManager] = None
    meet_orchestrator: Optional[MeetInterviewOrchestrator] = None
    combined_analyzer: Optional[CombinedAnalyzer] = None
    stt_service: Optional[STTService] = None
    tts_service: Optional[TTSService] = None

services = ServiceContainer()

def initialize_interview_services():
    try:
        # FIX 1: Increase urllib3 connection pool size BEFORE initializing services
        # This prevents "Connection pool is full" warnings
        urllib3.PoolManager(num_pools=50, maxsize=100)
        logger.info("✓ urllib3 connection pool configured (maxsize=100)")
        
        # 1. Database (Infrastructure Layer)
        try:
            services.db_handler = MongoSessionRepository()
            logger.info("MongoSessionRepository initialized")
            
            # Initialize concurrency limiter with DB handler
            init_concurrency_limiter(services.db_handler, max_sessions=5)
        except Exception as e:
            raise ServiceInitializationError("Database Repository", str(e))
        
        # 2. Analysis Services (Initialize BEFORE InterviewService)
        try:
            services.transcript_parser = TranscriptParser()
            services.transcript_analyzer = TranscriptAnalyzer(services.db_handler)
            services.combined_analyzer = CombinedAnalyzer(db_handler=services.db_handler)
            logger.info("Analysis services initialized (Singleton)")
        except Exception as e:
            raise ServiceInitializationError("Analysis Services", str(e))
            
        # 3. Session & Audio Managers
        try:
            services.meet_session_mgr = MeetSessionManager(services.db_handler)
            services.audio_handler = AudioHandler()
            services.stt_service = STTService(services.meet_session_mgr, services.db_handler)
            
            logger.info("Session & Audio managers initialized")
        except Exception as e:
            raise ServiceInitializationError("Session/Audio Managers", str(e))
        
        # 4. Core Logic Services (Dependency Injection)
        try:
            services.interview_service = InterviewService(
                db_handler=services.db_handler,
                combined_analyzer=services.combined_analyzer 
            )
            logger.info("Core Interview Service initialized (with injected Analyzer)")
        except Exception as e:
            raise ServiceInitializationError("Core Services", str(e))
        
        # 5. Audio Output (TTS)
        try:
            services.tts_service = TTSService(services.db_handler)
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

        logger.info("✓ All interview services initialized successfully (Singleton Pattern Enforced)")
        
    except ServiceInitializationError:
        raise
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to initialize interview services: {e}", exc_info=True)
        raise ServiceInitializationError("Unknown Service", str(e))

def get_services() -> ServiceContainer:
    return services
