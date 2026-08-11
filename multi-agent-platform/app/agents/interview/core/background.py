# app/core/background.py
import logging
import asyncio
import time
import json
from typing import Optional
from pathlib import Path

from app.agents.interview.config.constants import SessionStatus, BrowserConfig
from app.agents.interview.core.limiter import get_concurrency_limiter
from app.agents.interview.core.local_state import save_terminal_status
from app.agents.interview.core.startup import get_services
from app.agents.interview.core.session_error_tracker import (
    clear_session_errors,
    get_session_errors,
    install_session_error_log_handler,
    record_session_error,
    reset_error_tracking_session,
    set_error_tracking_session,
)
from app.utils.webhook_outbox import enqueue_webhook
from app.core.config import settings

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
    webhook_url: Optional[str] = None,
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
    final_webhook_queued = False
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
            completion_status = meet_session_mgr.get_start_failure(session_id) or SessionStatus.ERROR_JOIN_FAILED
            record_session_error(session_id, "meet_session", "Bot join failed", "BotJoinError")
            return

        # Wait for candidate (Async)
        candidate_joined = await meet_session_mgr.wait_for_candidate(session_id)
        if not candidate_joined:
            completion_status = SessionStatus.ERROR_CANDIDATE_NO_SHOW
            record_session_error(
                session_id,
                "participant_monitor",
                "Candidate did not join within the allowed time or participant validation failed",
                "CandidateNoShow",
            )
            return

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

        # 5. Persist final webhook(s) for asynchronous delivery.  This keeps
        # report delivery off the interview event loop and survives a restart.
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
                    "Using fallback final report for webhook because analysis output was empty. "
                    f"session_id={session_id}, status={orchestration_status}"
                )

            if final_report:
                session_errors = get_session_errors(session_id)
                final_report = _attach_agent_errors(final_report, session_errors)
                # 1. Actionabl Webhook Integration
                actionabl_url = settings.ACTIONABL_API_URL
                if actionabl_url:
                    logger.info(f"Queueing final JSON report to Actionabl API: {actionabl_url}")
                    headers = {
                        "Content-Type": "application/json"
                    }
                    if settings.ACTIONABL_AUTH_TOKEN:
                        headers["Authorization"] = f"Bearer {settings.ACTIONABL_AUTH_TOKEN}"
                    if settings.ACTIONABL_AUTH_ID:
                        headers["auth-id"] = settings.ACTIONABL_AUTH_ID
                        
                    actionabl_payload = {
                        "event": "analysis_completed",
                        "session_id": session_id,
                        "analysis": json.dumps(final_report),
                        "agent_errors": session_errors,
                    }
                        
                    enqueue_webhook(
                        actionabl_url, 
                        actionabl_payload,
                        headers=headers
                    )
                    final_webhook_queued = True
                
                # 2. Original Webhook Integration (Optional, can be kept or removed based on preference)
                if webhook_url:
                    logger.info(f"Queueing standard webhook to {webhook_url}")
                    enqueue_webhook(webhook_url, {
                        "event": "analysis_completed",
                        "session_id": session_id,
                        "transcript_path": str(transcript_path),
                        "analysis": json.dumps(final_report),
                        "agent_errors": session_errors,
                    })
                    final_webhook_queued = True
                    
                # Always cleanup if we successfully generated the report, regardless of webhook success
                await _cleanup_in_memory_session(
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

    except asyncio.CancelledError:
        completion_status = SessionStatus.ERROR_FATAL_TASK
        record_session_error(session_id, "task_runtime", "Interview task cancelled during shutdown", "TaskCancelled")
        raise
    except Exception as e:
        logger.error(f"FATAL ERROR: {e}", exc_info=True)
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
            save_terminal_status(session_id, terminal_status)
        except Exception:
            logger.exception("Could not save terminal interview status for %s", session_id)
        if not final_webhook_queued:
            try:
                _queue_terminal_notifications(
                    session_id=session_id,
                    completion_status=terminal_status,
                    session_errors=get_session_errors(session_id),
                    webhook_url=webhook_url,
                )
            except Exception:
                logger.exception("Could not persist terminal webhook event for %s", session_id)
        clear_session_errors(session_id)
        reset_error_tracking_session(error_tracking_token)


async def _cleanup_in_memory_session(session_id, interview_service, meet_session_mgr, concurrency_limiter):
    """Clear per-session memory after final report delivery succeeds."""
    if interview_service:
        interview_service.cleanup_session_state(session_id)
    if meet_session_mgr:
        await meet_session_mgr.end_session(session_id)
    if concurrency_limiter:
        concurrency_limiter.release(session_id)
    logger.info(f"In-memory session data cleaned after webhook success for {session_id}")


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


def _queue_terminal_notifications(
    session_id: str,
    completion_status: str,
    session_errors: list[dict],
    webhook_url: Optional[str],
) -> None:
    """Queue an error/no-show result to every configured final-report sink."""
    payload = {
        "event": "interview_completed",
        "session_id": session_id,
        "status": completion_status,
        "agent_errors": session_errors,
    }
    actionabl_url = settings.ACTIONABL_API_URL
    if actionabl_url:
        headers = {"Content-Type": "application/json"}
        if settings.ACTIONABL_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {settings.ACTIONABL_AUTH_TOKEN}"
        if settings.ACTIONABL_AUTH_ID:
            headers["auth-id"] = settings.ACTIONABL_AUTH_ID
        enqueue_webhook(actionabl_url, payload, headers=headers)
    if webhook_url:
        enqueue_webhook(webhook_url, payload)
