# app/api/interview.py
import logging
import io
import json
import uuid
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Request, Response

from app.agents.interview.core.startup import get_services
from app.agents.interview.core.background import start_and_conduct_interview_task
from app.core.exceptions import (
    ValidationError,
    InterviewExecutionError
)
from app.agents.interview.utils.resume_parser import parse_resume_pdf
from app.agents.interview.core.limiter import get_concurrency_limiter, RATE_LIMITS, limiter

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/start-google-meet", status_code=202)
@limiter.limit(RATE_LIMITS["start_interview"])
async def start_google_meet_interview(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    meet_link: str = Form(...),
    questionnaire_json: Optional[str] = Form(None),
    audio_device: Optional[int] = Form(None),
    enable_video: bool = Form(True),
    job_role: str = Form(...),
    job_description: Optional[str] = Form(None),
    video_capture_method: str = Form("javascript"),
    webhook_url: Optional[str] = Form(None),
    resume: UploadFile = File(...)
):
    """
    Start a new Google Meet interview session (Stateless).
    Generates a UUID session_id and dispatches background task.
    """
    logger.info(f"Starting interview for role: {job_role}")
    
    services = get_services()
    concurrency_limiter = get_concurrency_limiter()
    
    # === CONCURRENCY CHECK ===
    if concurrency_limiter:
        active_count = concurrency_limiter.get_active_count()
        if active_count >= concurrency_limiter.max_sessions:
            logger.warning(f"Concurrency limit reached: {active_count}/{concurrency_limiter.max_sessions}")
            raise HTTPException(
                status_code=503,
                detail=f"Server at capacity. {active_count} interviews currently running.",
                headers={"Retry-After": "60"}
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
            if not isinstance(questionnaire, list) or not all(isinstance(item, str) for item in questionnaire):
                raise ValidationError("questionnaire_json", "Must be a JSON array of strings")
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError("questionnaire_json", f"Invalid format: {str(e)}")

    # 3. Create session_id
    session_id = str(uuid.uuid4())
    logger.info(f"Generated Session ID: {session_id}")

    # 4. Schedule background task
    slot_acquired = False
    try:
        if concurrency_limiter:
            slot_acquired = concurrency_limiter.try_acquire(session_id)
            if not slot_acquired:
                raise HTTPException(status_code=503, detail="Server capacity reached")

        services.interview_service.start_new_interview(
            resume_text=resume_content,
            job_role=job_role,
            questionnaire=questionnaire,
            job_description=job_description,
            session_id=session_id
        )

        background_tasks.add_task(
            start_and_conduct_interview_task,
            session_id=session_id,
            meet_link=meet_link,
            webhook_url=webhook_url,
            audio_device=audio_device,
            enable_video=enable_video,
            video_capture_method=video_capture_method,
            job_role=job_role,
            resume_content=resume_content
        )
        
    except Exception as e:
        if concurrency_limiter and slot_acquired:
            concurrency_limiter.release(session_id)
        logger.error(f"Failed to schedule task: {e}", exc_info=True)
        if isinstance(e, HTTPException): raise e
        raise InterviewExecutionError(session_id, "task_scheduling", str(e))
    
    return {"status": "pending", "session_id": session_id}

@router.get("/{session_id}/status")
async def get_interview_status(session_id: str):
    """
    Check if a session is still active or completed.
    Stateless check: presence of report on disk.
    """
    report_path = Path("data") / session_id / "reports" / "final_screening_report.json"
    if report_path.exists():
        return {"status": "completed", "session_id": session_id}

    services = get_services()
    if services.meet_session_mgr and services.meet_session_mgr.get_session(session_id):
        return {"status": "active", "session_id": session_id}
    
    # Note: This is an approximation since we don't have a shared DB state
    return {"status": "active_or_not_found", "session_id": session_id}

@router.post("/{session_id}/end")
async def end_interview(session_id: str):
    """Request an active interview session to stop."""
    services = get_services()
    if not services.meet_session_mgr:
        raise HTTPException(status_code=503, detail="Session manager unavailable")
    
    try:
        if not services.meet_session_mgr.request_session_stop(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "ending", "session_id": session_id}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))
