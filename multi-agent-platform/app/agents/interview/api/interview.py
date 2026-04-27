# app/api/interview.py
import logging
import io
import json
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Request, Response

from app.agents.interview.config.constants import SessionStatus
from app.agents.interview.core.startup import get_services
from app.agents.interview.core.background import start_and_conduct_interview_task
from app.core.exceptions import (
    ServiceInitializationError,
    SessionNotFoundError,
    ValidationError,
    InterviewExecutionError,
    DatabaseError
)
from app.agents.interview.utils.resume_parser import parse_resume_pdf
from app.agents.interview.core.startup import services
from app.agents.interview.core.limiter import limiter, get_concurrency_limiter, RATE_LIMITS

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/start-google-meet", status_code=202)
@limiter.limit(RATE_LIMITS["start_interview"])
async def start_google_meet_interview(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    candidate_id: str = Form(...),
    meet_link: str = Form(...),
    questionnaire_json: Optional[str] = Form(None),
    audio_device: Optional[int] = Form(None),
    enable_video: bool = Form(True),
    job_role: str = Form(...),
    job_description: Optional[str] = Form(None),
    video_capture_method: str = Form("javascript"),
    resume: UploadFile = File(...)
):
    """Start a new Google Meet interview session (Rate limited: 2/min, Concurrency limited)"""
    logger.info(f"Starting interview for role: {job_role}")
    
    services = get_services()
    concurrency_limiter = get_concurrency_limiter()
    
    # === CONCURRENCY CHECK ===
    if concurrency_limiter:
        # Pre-check: Generate a temporary session ID for concurrency tracking
        # The actual session_id will be created later, but we check capacity first
        active_count = concurrency_limiter.get_active_count()
        if active_count >= concurrency_limiter.max_sessions:
            logger.warning(f"Concurrency limit reached: {active_count}/{concurrency_limiter.max_sessions}")
            raise HTTPException(
                status_code=503,
                detail=f"Server at capacity. {active_count} interviews currently running. Please try again later.",
                headers={"Retry-After": "60"}
            )
    
    # Verify services are available
    if not all([
        services.db_handler,
        services.interview_service,
        services.meet_session_mgr,
        services.meet_orchestrator,
        services.combined_analyzer
    ]):
        raise ServiceInitializationError(
            "Required Services",
            "One or more essential services are not available",
            {"available_services": {
                "db_handler": services.db_handler is not None,
                "interview_service": services.interview_service is not None,
                "meet_session_mgr": services.meet_session_mgr is not None,
                "meet_orchestrator": services.meet_orchestrator is not None,
                "combined_analyzer": services.combined_analyzer is not None
            }}
        )

    # 1. Parse Resume
    resume_content: Optional[str] = None
    try:
        resume_bytes = await resume.read()
        fname = resume.filename.lower() if resume.filename else ""
        
        if fname.endswith('.pdf') or fname.endswith('.docx'):
            resume_content = parse_resume_pdf(io.BytesIO(resume_bytes))
        elif fname.endswith('.txt'):
            resume_content = resume_bytes.decode("utf-8")
        else:
            raise ValidationError("resume", "Invalid file type. Supported: .pdf, .docx, .txt")
            
        if not resume_content:
            raise ValidationError("resume", "Resume file is empty")
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError("resume", f"Failed to parse resume: {str(e)}")

    # 2. Parse Questionnaire
    questionnaire: List[str] = []
    if questionnaire_json:
        try:
            questionnaire = json.loads(questionnaire_json)
            if not isinstance(questionnaire, list):
                raise ValidationError("questionnaire_json", "Must be a JSON array of strings")
        except json.JSONDecodeError as e:
            raise ValidationError("questionnaire_json", f"Invalid JSON format: {str(e)}")
        except Exception as e:
            raise ValidationError("questionnaire_json", f"Invalid format: {str(e)}")

    # 3. Create session
    session_id: Optional[str] = None
    slot_acquired = False
    try:
        session_id = services.interview_service.start_new_interview(
            resume_text=resume_content,
            candidate_id=candidate_id,
            job_role=job_role,
            questionnaire=questionnaire,
            job_description=job_description
        )
    except Exception as e:
        logger.error(f"Failed to create DB session: {e}", exc_info=True)
        raise DatabaseError("create_session", str(e))

    # 4. Schedule background task
    try:
        if concurrency_limiter and session_id:
            slot_acquired = concurrency_limiter.try_acquire(session_id)
            if not slot_acquired:
                services.interview_service.end_interview_session(session_id)
                services.db_handler.update_session_status(session_id, SessionStatus.ERROR_CAPACITY_REACHED)
                raise HTTPException(
                    status_code=503,
                    detail="Server reached interview capacity. Please try again later.",
                    headers={"Retry-After": "60"}
                )

        background_tasks.add_task(
            start_and_conduct_interview_task,
            session_id=session_id,
            candidate_id=candidate_id,
            meet_link=meet_link,
            audio_device=audio_device,
            enable_video=enable_video,
            video_capture_method=video_capture_method,
            job_role=job_role,
            resume_content=resume_content
        )
        
        services.db_handler.update_session_status(session_id, SessionStatus.ACTIVE_SCHEDULED)
    except Exception as e:
        if session_id:
            try:
                services.interview_service.end_interview_session(session_id)
            except Exception:
                logger.warning(f"Failed to finalize unscheduled session {session_id}", exc_info=True)
        if concurrency_limiter and slot_acquired and session_id:
            concurrency_limiter.release(session_id)
        logger.error(f"Failed to schedule interview task: {e}", exc_info=True)
        if isinstance(e, HTTPException):
            raise
        raise InterviewExecutionError(session_id, "task_scheduling", str(e))
    
    return {"status": SessionStatus.PENDING, "session_id": session_id}

@router.get("/{session_id}/status")
@limiter.limit(RATE_LIMITS["get_status"])
async def get_interview_status(request: Request, response: Response, session_id: str) -> Dict[str, Any]:
    """Get the current status of an interview session (Rate limited: 60/min)"""
    services = get_services()
    
    if not services.db_handler or not services.meet_session_mgr:
        raise ServiceInitializationError(
            "Required Services",
            "Database or session manager unavailable"
        )
    
    try:
        session_data = services.db_handler.get_session(session_id)
        if not session_data:
            raise SessionNotFoundError(session_id)
    except SessionNotFoundError:
        raise
    except Exception as e:
        raise DatabaseError("get_session", str(e), details={"session_id": session_id})
    
    try:
        active_session = services.meet_session_mgr.get_session(session_id)
        snapshot_count = services.meet_session_mgr.get_snapshot_count(session_id)
        bot_status = active_session.get('status', 'active') if active_session else "ended_or_unknown"
    except Exception as e:
        logger.error(f"Error getting session status: {e}", exc_info=True)
        raise InterviewExecutionError(session_id, "status_retrieval", str(e))
    
    return {
        "session_id": session_id,
        "status": session_data.get("status", "unknown"),
        "bot_status": bot_status,
        "snapshots": snapshot_count
    }

@router.post("/{session_id}/end")
async def end_interview(session_id: str):
    """Request an active interview session to stop and let background cleanup finalize it."""
    logger.info(f"Received request to end session: {session_id}")
    
    services = get_services()
    
    if not services.meet_session_mgr:
        raise HTTPException(status_code=503, detail="Session manager not initialized")
    
    session = services.meet_session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        services.meet_session_mgr.request_session_stop(session_id)
        return {"status": "ending", "session_id": session_id}
    except Exception as e:
        logger.error(f"Failed to end session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}/snapshots")
@limiter.limit(RATE_LIMITS["get_snapshots"])
async def get_snapshot_info(request: Request, response: Response, session_id: str):
    """Get snapshot count for a session (Rate limited: 30/min)"""
    services = get_services()
    
    if not services.meet_session_mgr:
        raise ServiceInitializationError("Session Manager", "Meet session manager unavailable")
    
    try:
        count = services.meet_session_mgr.get_snapshot_count(session_id)
    except Exception as e:
        logger.error(f"Error getting snapshot count: {e}", exc_info=True)
        raise InterviewExecutionError(session_id, "snapshot_retrieval", str(e))
    
    return {"session_id": session_id, "snapshots": count}
