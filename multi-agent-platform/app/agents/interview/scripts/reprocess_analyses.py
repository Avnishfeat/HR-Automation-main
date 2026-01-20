# app/scripts/reprocess_analyses.py
import asyncio
import logging
from app.infrastructure.database.mongo_session_repository import MongoSessionRepository
from app.services.gemini_service import GeminiService
# Import your Analysis Manager/Service here

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AnalysisRecovery")

async def reprocess_pending_sessions():
    db = MongoSessionRepository()
    gemini = GeminiService(db)
    
    # 1. Find stranded sessions
    pending_sessions = db.get_pending_analysis_sessions()
    
    if not pending_sessions:
        logger.info("No pending analyses found.")
        return

    logger.info(f"Found {len(pending_sessions)} sessions pending analysis. Starting recovery...")

    for session in pending_sessions:
        session_id = str(session["_id"])
        try:
            # Reuse the EXACT same logic you use in the main flow
            # (Assuming you put the logic in InterviewService or similar)
            logger.info(f"Reprocessing {session_id}...")
            
            # ... Call your generate_post_interview_analysis(session_id) here ...
            
        except Exception as e:
            logger.error(f"Failed to recover {session_id}: {e}")
            # Optional: Increment a 'retry_count' field in DB to prevent infinite loops

if __name__ == "__main__":
    asyncio.run(reprocess_pending_sessions())