# app/core/background.py
import logging
import threading
import asyncio
from typing import Optional
from pathlib import Path

from app.agents.interview.config.constants import SessionStatus, BrowserConfig
from app.agents.interview.core.limiter import get_concurrency_limiter
from app.agents.interview.core.startup import get_services
from app.utils.webhook_client import dispatch_webhook

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
    meet_link: str,
    webhook_url: Optional[str] = None,
    audio_device: Optional[int] = None,
    enable_video: bool = True,
    video_capture_method: str = "javascript",
    job_role: str = "Candidate",
    resume_content: str = "Not provided"
):
    """Background task - Stateless Local Storage Version"""
    logger.info(f"[Task: {session_id}] Background task started (Stateless)")

    services = get_services()
    meet_session_mgr = services.meet_session_mgr
    meet_orchestrator = services.meet_orchestrator
    combined_analyzer = services.combined_analyzer
    interview_service = services.interview_service
    concurrency_limiter = get_concurrency_limiter()

    snapshot_count = 0
    session_closed = False
    interview_state_closed = False
    interview_memory_cleaned = False
    concurrency_released = False
    candidate_name = interview_service.get_candidate_name(session_id) if interview_service else "Candidate"
    transcript_text = ""

    try:
        # 1. Start Bot
        success = meet_session_mgr.start_bot_session(
            session_id=session_id,
            meet_link=meet_link,
            audio_device=audio_device,
            enable_video=enable_video,
            headless=BrowserConfig.HEADLESS,
            video_capture_method=video_capture_method
        )
        if not success:
            if webhook_url:
                dispatch_webhook(webhook_url, {"event": "error", "session_id": session_id, "error": "Bot join failed"})
            return

        candidate_joined = meet_session_mgr.wait_for_candidate(session_id)
        if not candidate_joined:
            if webhook_url:
                dispatch_webhook(webhook_url, {
                    "event": "error",
                    "session_id": session_id,
                    "status": SessionStatus.ERROR_CANDIDATE_NO_SHOW,
                    "error": "Candidate did not join within the allowed time or participant validation failed"
                })
            return

        if enable_video:
            meet_session_mgr._start_candidate_video_capture(session_id)

        # 2. Conduct Interview
        try:
            async def run_conduct():
                return await meet_orchestrator.conduct_interview(session_id=session_id)

            asyncio.run(run_conduct())
        except Exception as e:
            logger.error(f"Orchestration failed: {e}", exc_info=True)

        # 3. Cleanup & Finalize Local Data
        snapshot_count = meet_session_mgr.get_snapshot_count(session_id)
        background_person_count = meet_session_mgr.get_background_person_count(session_id)
        reconnection_count = meet_session_mgr.get_reconnection_count(session_id)

        if interview_service:
            candidate_name = interview_service.get_candidate_name(session_id)
            interview_service.finalize_interview_session(session_id)

        if meet_session_mgr:
            meet_session_mgr.end_session(session_id)
            session_closed = True

        # 4. Trigger Analyses (Read from Disk)
        analysis_results = {"behavioral": None, "transcript": None, "voice": None}
        analysis_threads = []

        # Behavioral
        if enable_video and snapshot_count > 0:
            analysis_threads.append(threading.Thread(
                target=run_analysis_in_thread,
                args=(combined_analyzer.perform_behavioral_analysis, (session_id,), analysis_results, "behavioral"),
                daemon=True
            ))

        # Transcript & Voice
        transcript_path = Path("data") / session_id / "transcript.txt"
        if transcript_path.exists():
            transcript_text = transcript_path.read_text(encoding="utf-8")

            # Transcript
            analysis_threads.append(threading.Thread(
                target=run_analysis_in_thread,
                args=(combined_analyzer.transcript_analyzer.analyze,
                      (session_id, transcript_text, resume_content, job_role),
                      analysis_results, "transcript"),
                daemon=True
            ))
            # Voice
            analysis_threads.append(threading.Thread(
                target=run_analysis_in_thread,
                args=(combined_analyzer.perform_voice_authenticity_analysis,
                      (session_id,), analysis_results, "voice"),
                daemon=True
            ))

        # Run Threads
        for t in analysis_threads: t.start()
        for t in analysis_threads: t.join()

        # 5. Combine & Dispatch Webhook
        try:
            combined_report = combined_analyzer.combine_analyses(
                behavioral_result=analysis_results.get("behavioral"),
                transcript_result=analysis_results.get("transcript"),
                voice_result=analysis_results.get("voice"),
                session_id=session_id,
                candidate_name=candidate_name,
                background_person_count=background_person_count,
                reconnection_count=reconnection_count
            )

            if combined_report and webhook_url:
                report_data = combined_report.model_dump() if hasattr(combined_report, 'model_dump') else combined_report
                logger.info(f"Dispatching final report to {webhook_url}")
                webhook_sent = dispatch_webhook(webhook_url, {
                    "event": "analysis_completed",
                    "session_id": session_id,
                    "transcript": transcript_text,
                    "transcript_path": str(transcript_path),
                    "analysis": report_data
                })
                if webhook_sent:
                    _cleanup_in_memory_session(
                        session_id=session_id,
                        interview_service=interview_service,
                        meet_session_mgr=meet_session_mgr,
                        concurrency_limiter=concurrency_limiter,
                    )
                    interview_state_closed = True
                    interview_memory_cleaned = True
                    session_closed = True
                    concurrency_released = True
        except Exception as e:
            logger.error(f"Combined analysis/webhook failed: {e}")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}", exc_info=True)
        if webhook_url:
            dispatch_webhook(webhook_url, {"event": "fatal_error", "session_id": session_id, "error": str(e)})
    finally:
        if interview_service and not interview_state_closed:
            try:
                interview_service.end_interview_session(session_id)
            except Exception as e:
                logger.warning(f"Interview service cleanup failed for {session_id}: {e}")
        elif interview_service and not interview_memory_cleaned:
            try:
                interview_service.cleanup_session_state(session_id)
            except Exception as e:
                logger.warning(f"Interview service memory cleanup failed for {session_id}: {e}")
        if meet_session_mgr and not session_closed:
            meet_session_mgr.end_session(session_id)
        if concurrency_limiter and not concurrency_released:
            concurrency_limiter.release(session_id)


def _cleanup_in_memory_session(session_id, interview_service, meet_session_mgr, concurrency_limiter):
    """Clear per-session memory after final report delivery succeeds."""
    if interview_service:
        interview_service.cleanup_session_state(session_id)
    if meet_session_mgr:
        meet_session_mgr.end_session(session_id)
    if concurrency_limiter:
        concurrency_limiter.release(session_id)
    logger.info(f"In-memory session data cleaned after webhook success for {session_id}")
