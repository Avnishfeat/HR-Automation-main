# app/api/interview.py
import logging
import io
import json
import uuid
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.agents.interview.core.startup import get_services
from app.agents.interview.core.background import start_and_conduct_interview_task
from app.agents.interview.core.task_registry import (
    clear_interview_task_operator_termination,
    create_interview_task,
    is_task_active,
    mark_interview_task_operator_terminated,
)
from app.agents.interview.config.constants import TERMINAL_SESSION_STATUSES
from app.agents.interview.database import (
    create_or_get_interview,
    delete_pending_interview,
    get_interview_by_buss_id,
    get_interview_by_idempotency_key,
    normalize_idempotency_key,
)
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
    meet_link: str = Form(...),
    questionnaire_json: Optional[str] = Form(None),
    audio_device: Optional[int] = Form(None),
    enable_video: bool = Form(True),
    job_role: str = Form(...),
    job_description: Optional[str] = Form(None),
    video_capture_method: str = Form("javascript"),
    candidate_email: str = Form(...),
    buss_id: str = Form(...),
    resume: UploadFile = File(...),
    idempotency_key_header: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    Start a new Google Meet interview session (Stateless).
    Generates a UUID session_id and dispatches background task.
    """
    try:
        idempotency_key = normalize_idempotency_key(idempotency_key_header)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    buss_id = buss_id.strip()
    if not buss_id:
        raise HTTPException(status_code=400, detail="buss_id must not be blank")

    # Return the original accepted response before capacity checks or file parsing.
    # Either the unique buss_id or an explicit idempotency key can safely replay it.
    existing = await get_interview_by_buss_id(buss_id)
    if not existing and idempotency_key:
        existing = await get_interview_by_idempotency_key(idempotency_key)
    if existing:
        response.headers["Idempotent-Replay"] = "true"
        return {
            "status": existing.status,
            "session_id": existing.session_id,
            "idempotent_replay": True,
        }

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

        interview, created = await create_or_get_interview(
            session_id=session_id,
            buss_id=buss_id,
            candidate_email=candidate_email,
            job_role=job_role,
            job_description=job_description,
            idempotency_key=idempotency_key,
        )
        if not created:
            if concurrency_limiter and slot_acquired:
                concurrency_limiter.release(session_id)
            response.headers["Idempotent-Replay"] = "true"
            return {
                "status": interview.status,
                "session_id": interview.session_id,
                "idempotent_replay": True,
            }

        services.interview_service.start_new_interview(
            resume_text=resume_content,
            job_role=job_role,
            questionnaire=questionnaire,
            job_description=job_description,
            session_id=session_id
        )

        create_interview_task(
            session_id,
            start_and_conduct_interview_task(
            session_id=session_id,
            meet_link=meet_link,
            audio_device=audio_device,
            enable_video=enable_video,
            video_capture_method=video_capture_method,
            job_role=job_role,
            resume_content=resume_content,
            candidate_email=candidate_email,
            buss_id=buss_id
            ),
        )
    except Exception as e:
        if concurrency_limiter and slot_acquired:
            concurrency_limiter.release(session_id)
        await delete_pending_interview(session_id)
        logger.error(f"Failed to schedule task: {e}", exc_info=True)
        if isinstance(e, HTTPException): raise e
        raise InterviewExecutionError(session_id, "task_scheduling", str(e))
    
    return {"status": "pending", "session_id": session_id}


@router.get("/analysis/{buss_id}")
async def get_interview_analysis(buss_id: str):
    """Return a full terminal report, or a polling response while it is pending."""
    interview = await get_interview_by_buss_id(buss_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    payload = {
        "buss_id": interview.buss_id,
        "session_id": interview.session_id,
        "status": interview.status,
        "terminal_reason": interview.terminal_reason,
        "analysis": interview.analysis_json,
        "agent_errors": interview.agent_errors or [],
        "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
    }
    if interview.status not in TERMINAL_SESSION_STATUSES:
        payload["retry_after_seconds"] = 15
        return JSONResponse(status_code=202, content=payload)
    return payload

@router.get("/{session_id}/status")
async def get_interview_status(session_id: str):
    """
    Check a session's persisted lifecycle status, retaining an in-process
    fallback for legacy callers while a task is starting.
    """
    # This endpoint remains session-based for existing callers; the new analysis
    # endpoint is the third-party retrieval API keyed by buss_id.
    from app.agents.interview.database import Interview, database_session
    async with database_session() as session:
        interview = await session.get(Interview, session_id)
    if interview:
        return {"status": interview.status, "session_id": interview.session_id}

    services = get_services()
    if is_task_active(session_id) or (services.meet_session_mgr and services.meet_session_mgr.get_session(session_id)):
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
        # Mark before signalling the browser: its wait loop may immediately
        # return false once the stop event is set.
        mark_interview_task_operator_terminated(session_id)
        if not services.meet_session_mgr.request_session_stop(session_id):
            clear_interview_task_operator_termination(session_id)
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "ending", "session_id": session_id}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))
