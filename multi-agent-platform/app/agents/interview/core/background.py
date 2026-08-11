# app/core/background.py
import logging
import asyncio
import time
from typing import Optional
from pathlib import Path

from app.agents.interview.config.constants import BrowserConfig, InterruptionReason, SessionStatus
from app.agents.interview.core.limiter import get_concurrency_limiter
from app.agents.interview.core.local_state import save_terminal_status
from app.agents.interview.core.task_registry import is_interview_shutdown_requested
from app.agents.interview.database import complete_interview, update_interview_status
from app.agents.interview.core.startup import get_services
from app.agents.interview.core.session_error_tracker import (
    clear_session_errors,
    get_session_errors,
    install_session_error_log_handler,
    record_session_error,
    reset_error_tracking_session,
    set_error_tracking_session,
)

logger = logging.getLogger(__name__)

async def run_analysis_in_thread(target_func, args_tuple, results_dict, key_name):
    """Runs a target synchronous function in an asyncio thread and stores result/error in dict"""
    try:
        logger.info(f"Starting analysis task for '{key_name}'...")
        result = await asyncio.to_thread(target_func, *args_tuple)
        results_dict[key_name] = result
        logger.info(f"Analysis task '{key_name}' completed successfully")
    except Exception as e:
        logger.error(f"Error in analysis task '{key_name}': {e}", exc_info=True)
        results_dict[key_name] = None

async def start_and_conduct_interview_task(
    session_id: str,
    meet_link: str,
    audio_device: Optional[int] = None,
    enable_video: bool = True,
    video_capture_method: str = "javascript",
    job_role: str = "Candidate",
    resume_content: str = "Not provided",
    candidate_email: str = "Not provided",
    buss_id: str = "Not provided"
):
    """Background task - Stateless Local Storage Version (Async)"""
    logger.info(f"[Task: {session_id}] Background task started (Stateless/Async)")

    meet_session_mgr = None
    meet_orchestrator = None
    combined_analyzer = None
    interview_service = None
    concurrency_limiter = None
    session_closed = False
    interview_state_closed = False
    interview_memory_cleaned = False
    concurrency_released = False
    candidate_name = "Candidate"
    transcript_text = ""
    completion_status: Optional[str] = None
    terminal_reason: Optional[str] = None
    final_report: Optional[dict] = None
    install_session_error_log_handler()
    error_tracking_token = set_error_tracking_session(session_id)

    try:
        services = get_services()
        meet_session_mgr = services.meet_session_mgr
        meet_orchestrator = services.meet_orchestrator
        combined_analyzer = services.combined_analyzer
        interview_service = services.interview_service
        concurrency_limiter = get_concurrency_limiter()
        candidate_name = interview_service.get_candidate_name(session_id) if interview_service else "Candidate"
        await update_interview_status(session_id, "joining")

        # 1. Start Bot (Async)
        success = await meet_session_mgr.start_bot_session(
            session_id=session_id,
            meet_link=meet_link,
            audio_device=audio_device,
            enable_video=enable_video,
            headless=BrowserConfig.HEADLESS,
            video_capture_method=video_capture_method
        )
        if not success:
            if is_interview_shutdown_requested(session_id):
                completion_status = SessionStatus.INTERRUPTED
                terminal_reason = InterruptionReason.BACKEND_SHUTDOWN
            else:
                completion_status = meet_session_mgr.get_start_failure(session_id) or SessionStatus.ERROR_JOIN_FAILED
                record_session_error(session_id, "meet_session", "Bot join failed", "BotJoinError")
            return

        # Wait for candidate (Async)
        candidate_joined = await meet_session_mgr.wait_for_candidate(session_id)
        if not candidate_joined:
            if is_interview_shutdown_requested(session_id):
                completion_status = SessionStatus.INTERRUPTED
                terminal_reason = InterruptionReason.BACKEND_SHUTDOWN
            else:
                completion_status = SessionStatus.ERROR_CANDIDATE_NO_SHOW
                record_session_error(
                    session_id,
                    "participant_monitor",
                    "Candidate did not join within the allowed time or participant validation failed",
                    "CandidateNoShow",
                )
            return

        await update_interview_status(session_id, "interviewing")

        if enable_video:
            meet_session_mgr._start_candidate_video_capture(session_id)

        # 2. Conduct Interview (Async)
        interview_start_time = time.time()
        orchestration_result = {}
        try:
            orchestration_result = await meet_orchestrator.conduct_interview(session_id=session_id)
        except Exception as e:
            logger.error(f"Orchestration failed: {e}", exc_info=True)
            orchestration_result = None
            
        duration_sec = int(time.time() - interview_start_time)
        orchestration_status = None
        ended_early = False
        if isinstance(orchestration_result, dict):
            orchestration_status = orchestration_result.get("status")
            completion_status = orchestration_status or SessionStatus.ERROR_FATAL_TASK
            if orchestration_status and orchestration_status != SessionStatus.COMPLETED:
                ended_early = True
        else:
            completion_status = SessionStatus.ERROR_FATAL_TASK
            ended_early = True # Fallback if we didn't get a proper dict

        if is_interview_shutdown_requested(session_id):
            completion_status = SessionStatus.INTERRUPTED
            terminal_reason = InterruptionReason.BACKEND_SHUTDOWN

        # 3. Cleanup & Finalize Local Data
        snapshot_count = meet_session_mgr.get_snapshot_count(session_id)
        background_person_count = meet_session_mgr.get_background_person_count(session_id)
        reconnection_count = meet_session_mgr.get_reconnection_count(session_id)

        if interview_service:
            candidate_name = interview_service.get_candidate_name(session_id)
            interview_service.finalize_interview_session(session_id)

        if meet_session_mgr:
            await meet_session_mgr.end_session(session_id)
            session_closed = True

        # 4. Trigger Analysis (Single Call)
        await update_interview_status(session_id, "analyzing")
        transcript_path = Path("data") / session_id / "transcript.txt"
        if transcript_path.exists():
            transcript_text = transcript_path.read_text(encoding="utf-8")
        else:
            transcript_text = "No transcript generated."

        analysis_results = {"final_report": None}
        analysis_tasks = [
            run_analysis_in_thread(
                combined_analyzer.generate_final_report,
                (
                    session_id,
                    transcript_text,
                    resume_content,
                    job_role,
                    candidate_name,
                    duration_sec,
                    ended_early,
                    background_person_count,
                    reconnection_count,
                    candidate_email,
                    buss_id
                ),
                analysis_results,
                "final_report"
            )
        ]

        await asyncio.gather(*analysis_tasks)

        # 5. Build the final report. Delivery is database retrieval only; no
        # outbound webhook is sent after this point.
        try:
            final_report = analysis_results.get("final_report")
            if not final_report:
                final_report = _build_fallback_final_report(
                    session_id=session_id,
                    candidate_name=candidate_name,
                    candidate_email=candidate_email,
                    buss_id=buss_id,
                    job_role=job_role,
                    duration_sec=duration_sec,
                    ended_early=ended_early,
                    orchestration_status=orchestration_status,
                    transcript_text=transcript_text,
                    background_person_count=background_person_count,
                    reconnection_count=reconnection_count,
                )
                logger.warning(
                    "Using fallback final report because analysis output was empty. "
                    f"session_id={session_id}, status={orchestration_status}"
                )
        except Exception as e:
            logger.error(f"Combined analysis persistence preparation failed: {e}")

    except asyncio.CancelledError:
        completion_status = SessionStatus.INTERRUPTED
        terminal_reason = InterruptionReason.BACKEND_SHUTDOWN
        record_session_error(session_id, "task_runtime", "Interview task cancelled during shutdown", "TaskCancelled")
        raise
    except Exception as e:
        logger.error(f"FATAL ERROR: {e}", exc_info=True)
        if is_interview_shutdown_requested(session_id):
            completion_status = SessionStatus.INTERRUPTED
            terminal_reason = InterruptionReason.BACKEND_SHUTDOWN
        else:
            completion_status = SessionStatus.ERROR_FATAL_TASK
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
            await meet_session_mgr.end_session(session_id)
        if concurrency_limiter and not concurrency_released:
            concurrency_limiter.release(session_id)
        terminal_status = completion_status or SessionStatus.ERROR_FATAL_TASK
        try:
            session_errors = get_session_errors(session_id)
            final_report = _attach_agent_errors(final_report, session_errors) if final_report else None
            await complete_interview(
                session_id,
                terminal_status,
                final_report,
                session_errors,
                terminal_reason=terminal_reason,
            )
            # The database is the source of truth. This marker solely lets the
            # conservative local-media retention task identify terminal folders.
            save_terminal_status(session_id, terminal_status)
        except Exception:
            logger.exception("Could not save terminal interview record for %s", session_id)
        clear_session_errors(session_id)
        reset_error_tracking_session(error_tracking_token)


def _build_fallback_final_report(
    session_id: str,
    candidate_name: str,
    candidate_email: str,
    buss_id: str,
    job_role: str,
    duration_sec: int,
    ended_early: bool,
    orchestration_status: Optional[str],
    transcript_text: str,
    background_person_count: int,
    reconnection_count: int,
):
    termination_reason = None
    flags = []

    if ended_early:
        flags.append("ended_interview_early")

    if orchestration_status == SessionStatus.TERMINATED_LIVENESS_FAIL:
        termination_reason = "mid_interview_liveness_failed"
        flags.append("mid_interview_liveness_failed")
    elif orchestration_status:
        termination_reason = orchestration_status
        flags.append(orchestration_status)

    return {
        "session_id": session_id,
        "candidate": {
            "name": candidate_name,
            "email": candidate_email,
            "buss_id": buss_id,
            "role": job_role,
        },
        "status": {
            "completed": orchestration_status == SessionStatus.COMPLETED,
            "ended_early": ended_early,
            "duration_sec": duration_sec,
            "termination_reason": termination_reason,
        },
        "scores": {
            "overall": None,
            "technical": None,
            "communication": None,
            "behavioral": None,
            "authenticity": 1.0 if orchestration_status == SessionStatus.TERMINATED_LIVENESS_FAIL else None,
        },
        "flags": flags,
        "summary": (
            "Interview ended because the candidate failed the mid-interview liveness check."
            if orchestration_status == SessionStatus.TERMINATED_LIVENESS_FAIL
            else "Interview ended before a generated analysis report was available."
        ),
        "recommendation": "review",
        "transcript": [],
        "raw_transcript": transcript_text or "No transcript generated.",
        "metadata": {
            "reconnections": reconnection_count,
            "background_persons": background_person_count,
            "analysis_fallback": True,
        },
    }


def _attach_agent_errors(final_report, session_errors):
    """Embed agent errors in dict-based reports without changing other report types."""
    if not isinstance(final_report, dict):
        return final_report

    report = dict(final_report)
    metadata = report.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    report["metadata"] = {
        **metadata,
        "agent_error_count": len(session_errors),
        "agent_errors": session_errors,
    }
    return report
