# app/core/background.py
import logging
import threading
import asyncio
from datetime import datetime
from typing import Optional
import concurrent.futures

from app.agents.interview.config.constants import SessionStatus, BrowserConfig
from app.agents.interview.core.limiter import get_concurrency_limiter
from app.agents.interview.core.startup import get_services
from app.core.exceptions import (ServiceInitializationError, MeetConnectionError, InterviewExecutionError)
from app.agents.interview.models.analysis_schemas import CombinedAnalysisReport

logger = logging.getLogger(__name__)

def run_analysis_in_thread(target_func, args_tuple, results_dict, key_name):
    """Runs a target function in a thread and stores result/error in dict"""
    try:
        logger.info(f"Starting analysis thread for '{key_name}'...")
        result = target_func(*args_tuple)
        results_dict[key_name] = result
        logger.info(f"Analysis thread '{key_name}' completed successfully")
    except Exception as e:
        logger.error(f"Error in analysis thread '{key_name}': {e}", exc_info=True)
        results_dict[key_name] = None

def start_and_conduct_interview_task(
    session_id: str,
    candidate_id: str,
    meet_link: str,
    audio_device: Optional[int],
    enable_video: bool,
    video_capture_method: str,
    job_role: str,
    resume_content: str
):
    """Background task - MongoDB Only Version"""
    logger.info(f"[Task: {session_id}] Background task started (DB Mode)")
    
    # Get services
    services = get_services()
    db_handler = services.db_handler
    meet_session_mgr = services.meet_session_mgr
    meet_orchestrator = services.meet_orchestrator
    interview_service = services.interview_service
    combined_analyzer = services.combined_analyzer
    transcript_analyzer = services.transcript_analyzer
    concurrency_limiter = get_concurrency_limiter()

    
    final_status = "error_unknown"
    snapshot_count = 0
    session_closed = False
    session_finalized = False

    try:
        # Check services...
        if not all([meet_session_mgr, meet_orchestrator, db_handler]):
            raise ServiceInitializationError("Background", "Services missing")

        # 1. Start Bot
        success = meet_session_mgr.start_bot_session(
            session_id, meet_link, candidate_id, audio_device,
            enable_video, BrowserConfig.HEADLESS, video_capture_method
        )
        if not success:
            db_handler.update_session_status(session_id, SessionStatus.ERROR_JOIN_FAILED)
            raise MeetConnectionError(session_id, "Bot join failed")

        if concurrency_limiter:
            concurrency_limiter.heartbeat(session_id)

        # 2. Wait for Candidate
        if not meet_session_mgr.wait_for_candidate(session_id, timeout=300):
            active_session = meet_session_mgr.get_session(session_id) if meet_session_mgr else None
            stop_requested = bool(
                active_session
                and active_session.get("stop_interview")
                and active_session["stop_interview"].is_set()
            )
            if stop_requested:
                logger.info(f"[Task: {session_id}] Stop requested before candidate joined")
                final_status = SessionStatus.COMPLETED_NO_ANALYSIS
                db_handler.update_session_status(session_id, SessionStatus.COMPLETED_NO_ANALYSIS)
                return

            db_handler.update_session_status(session_id, SessionStatus.ERROR_CANDIDATE_NO_SHOW)
            raise InterviewExecutionError(session_id, "wait", "Candidate no-show")

        db_handler.update_session_status(session_id, SessionStatus.ACTIVE_INTERVIEWING)
        if concurrency_limiter:
            concurrency_limiter.heartbeat(session_id)

        # 3. Video Capture
        if enable_video:
            meet_session_mgr._start_candidate_video_capture(session_id)

        # 4. Conduct Interview
        try:
            # FIX: Optimized Thread Pool Size
            # The issue: 50 workers * multiple Gemini API calls = connection pool exhaustion
            # Solution: Use a smaller, more reasonable pool size (20 workers)
            # This is enough for:
            # - Audio generation (TTS) - I/O bound
            # - Speech recognition (STT) - I/O bound  
            # - Gemini API calls - I/O bound
            # - Video capture - CPU bound (runs in separate daemon thread)
            async def run_with_optimized_threads():
                loop = asyncio.get_running_loop()
                # Set to 20 workers (was 50, which was excessive)
                # I/O-bound tasks don't need many threads since they wait on network
                loop.set_default_executor(
                    concurrent.futures.ThreadPoolExecutor(max_workers=20)
                )
                logger.info(f"[Task: {session_id}] Thread Pool configured with 20 workers")
                return await meet_orchestrator.conduct_interview(session_id=session_id)

            result = asyncio.run(run_with_optimized_threads())
            
            final_status = result.get('status', 'completed_unknown')

        except Exception as e:
            raise InterviewExecutionError(session_id, "orchestration", str(e))
        
        # 5. Cleanup - GET COUNTS BEFORE ENDING SESSION
        snapshot_count = meet_session_mgr.get_snapshot_count(session_id)
        background_person_count = meet_session_mgr.get_background_person_count(session_id)
        reconnection_count = meet_session_mgr.get_reconnection_count(session_id)
        logger.info(f"[Task: {session_id}] Counts before cleanup - snapshots: {snapshot_count}, bg_persons: {background_person_count}, reconnects: {reconnection_count}")
        
        if meet_session_mgr:
            meet_session_mgr.end_session(session_id)
            session_closed = True
            
        if interview_service:
            interview_service.end_interview_session(session_id)
            session_finalized = True

        db_handler.update_session_status(session_id, SessionStatus.ACTIVE_ANALYZING)

        # 6. Retrieve Transcript (FROM DB)
        transcript_content = db_handler.get_transcript_text(session_id)
        
        if not transcript_content:
            logger.warning(f"[Task: {session_id}] Transcript empty in DB. Attempting reconstruction...")

        # 7. Run Analyses
        analysis_results = {"behavioral": None, "transcript": None, "voice": None}
        analysis_threads = []

        # Behavioral
        if enable_video and snapshot_count > 0:
            analysis_threads.append(threading.Thread(
                target=run_analysis_in_thread,
                args=(combined_analyzer.perform_behavioral_analysis, 
                      (candidate_id, session_id), analysis_results, "behavioral"),
                daemon=True
            ))

        # Transcript & Voice
        if transcript_content:
            # Transcript
            analysis_threads.append(threading.Thread(
                target=run_analysis_in_thread,
                args=(transcript_analyzer.analyze, 
                      (session_id,), analysis_results, "transcript"),
                daemon=True
            ))
            # Voice
            analysis_threads.append(threading.Thread(
                target=run_analysis_in_thread,
                args=(combined_analyzer.perform_voice_authenticity_analysis,
                      (candidate_id, session_id), analysis_results, "voice"),
                daemon=True
            ))

        # Run Threads
        for t in analysis_threads: t.start()
        for t in analysis_threads: t.join()

        # 8. Combine & Save (TO DB)
        try:
            combined_report: CombinedAnalysisReport = combined_analyzer.combine_analyses(
                behavioral_result=analysis_results.get("behavioral"),
                transcript_result=analysis_results.get("transcript"),
                voice_result=analysis_results.get("voice"),
                session_id=session_id,
                candidate_id=candidate_id,
                background_person_count=background_person_count,
                reconnection_count=reconnection_count
            )
            
            if combined_report:
                logger.info(f"[Task: {session_id}] Analysis completed and saved by Analyzer.")
                db_handler.update_session_status(session_id, SessionStatus.COMPLETED)
            else:
                logger.error(f"[Task: {session_id}] CombinedAnalyzer returned None.")
                db_handler.update_session_status(session_id, SessionStatus.ERROR_ANALYSIS_EMPTY)

        except Exception as e:
            logger.error(f"[Task: {session_id}] Combine failed: {e}", exc_info=True)
            db_handler.update_session_status(session_id, SessionStatus.ERROR_ANALYSIS_FAILED)

    except Exception as e:
        logger.error(f"FATAL ERROR [Task: {session_id}]: {e}", exc_info=True)
        if db_handler:
            db_handler.update_session_status(session_id, SessionStatus.ERROR_FATAL_TASK)
    finally:
        # Emergency Cleanup
        try:
            if meet_session_mgr and not session_closed:
                meet_session_mgr.end_session(session_id)
        except Exception:
            logger.warning(f"[Task: {session_id}] Emergency session cleanup failed", exc_info=True)

        try:
            if interview_service and not session_finalized:
                interview_service.end_interview_session(session_id)
        except Exception:
            logger.warning(f"[Task: {session_id}] Emergency interview finalization failed", exc_info=True)

        try:
            if concurrency_limiter:
                concurrency_limiter.release(session_id)
        except Exception:
            logger.warning(f"[Task: {session_id}] Failed to release concurrency slot", exc_info=True)
