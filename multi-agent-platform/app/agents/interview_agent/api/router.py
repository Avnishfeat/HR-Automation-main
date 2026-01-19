
# app/services/interview/api/router.py
import logging
import io
import json
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.agents.interview_agent.service_container import get_services, initialize_interview_services
from app.agents.interview_agent.tasks.background import start_and_conduct_interview_task
from app.agents.interview_agent.schemas import InterviewStatusResponse
from app.agents.interview_agent.utils.exceptions import (
    ServiceInitializationError,
    SessionNotFoundError,
    ValidationError,
    InterviewExecutionError,
    DatabaseError
)
# We need to port resume_parser too? Or use existing logic?
# Assumed app.services.interview.utils will have it or we copy it.
# Checking utils: audio_file_utils.py, constants.py, exceptions.py, limiter.py, retry_handler.py, transcript_parser.py
# No resume_parser. I will add a simple one or reference one if available.
# For now, I'll assume I need to handle it here or add resume_parser to utils.
# I'll add a simplified resume handler here to avoid dependency hell if possible.
from app.agents.interview_agent.utils.limiter import limiter, get_concurrency_limiter, RATE_LIMITS

logger = logging.getLogger(__name__)
router = APIRouter()

def parse_resume_text(file_bytes: bytes, filename: str) -> str:
    # Simplified parser
    try:
        if filename.endswith('.txt'):
            return file_bytes.decode('utf-8')
        if filename.endswith('.pdf'):
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        # docx support requires python-docx
        if filename.endswith('.docx'):
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join([para.text for para in doc.paragraphs])
            
        return ""
    except Exception as e:
        logger.error(f"Resume parsing error: {e}")
        return ""

@router.on_event("startup")
async def startup_event():
    # Only if not initialized globaly.
    # But initialize_interview_services() is robust enough to run.
    initialize_interview_services()


@router.post("/start-google-meet", status_code=202)
@limiter.limit(RATE_LIMITS["start_interview"])
async def start_google_meet_interview(
    request: Request,  # Required for rate limiter
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
    """Start a new Google Meet interview session"""
    logger.info(f"Starting interview for role: {job_role}")
    
    services = get_services()
    
    # === CONCURRENCY CHECK ===
    concurrency_limiter = get_concurrency_limiter()
    if concurrency_limiter:
        active_count = await concurrency_limiter.get_active_count()
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
        # Try finding why
        logger.error("Services not available: db=%s, svc=%s", services.db_handler, services.interview_service)
        raise ServiceInitializationError(
            "Required Services",
            "One or more essential services are not available"
        )

    # 1. Parse Resume
    resume_content: Optional[str] = None
    try:
        resume_bytes = await resume.read()
        fname = resume.filename.lower() if resume.filename else ""
        resume_content = parse_resume_text(resume_bytes, fname)
            
        if not resume_content:
            raise ValidationError("resume", "Resume file is empty or could not be parsed")
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
    try:
        # start_new_interview is synchronous in interview_service (it handles async internally or wraps it?)
        # Step 392: start_new_interview calls self.db.create_session (async) using loop.
        # But here we are in async def. 
        # Calling services.interview_service.start_new_interview (sync) is fine.
        session_id = await services.interview_service.start_new_interview(
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
        
        # update_session_status is async. 
        # But we are in async def.
        await services.db_handler.update_session_status(session_id, "active_scheduled")
    except Exception as e:
        logger.error(f"Failed to schedule interview task: {e}", exc_info=True)
        raise InterviewExecutionError(session_id, "task_scheduling", str(e))
    
    return JSONResponse(
        status_code=201,
        content={"status": "pending", "session_id": session_id, "message": f"Interview session {session_id} initialized"}
    )

@router.get("/{session_id}/status", response_model=InterviewStatusResponse)
@limiter.limit(RATE_LIMITS["get_status"])
async def get_interview_status(request: Request, session_id: str) -> InterviewStatusResponse:
    """Get the current status of an interview session"""
    services = get_services()
    
    if not services.db_handler or not services.meet_session_mgr:
        raise ServiceInitializationError("Required Services", "Unavailable")
    
    try:
        session_data = await services.db_handler.get_session(session_id)
        if not session_data:
            raise SessionNotFoundError(session_id)
    except SessionNotFoundError:
        raise
    except Exception as e:
        raise DatabaseError("get_session", str(e), details={"session_id": session_id})
    
    try:
        active_session = services.meet_session_mgr.get_session(session_id)
        # Fix: Await async method
        snapshot_count = await services.meet_session_mgr.get_snapshot_count(session_id)
        bot_status = active_session.get('status', 'active') if active_session else "ended_or_unknown"
    except Exception as e:
        logger.error(f"Error getting session status: {e}", exc_info=True)
        raise InterviewExecutionError(session_id, "status_retrieval", str(e))
    
    return InterviewStatusResponse(
        session_id=session_id,
        status=session_data.get("status", "unknown"),
        candidate_id=session_data.get("candidate_id", "unknown"),
        meet_link=session_data.get("meet_link"),
        snapshot_count=snapshot_count,
        created_at=session_data.get("created_at"),
        message=f"Bot status: {bot_status}"
    )

@router.post("/{session_id}/end")
async def end_interview(session_id: str):
    """Manually end an active interview session"""
    logger.info(f"Received request to end session: {session_id}")
    
    services = get_services()
    
    if not services.meet_session_mgr:
        raise HTTPException(status_code=503, detail="Session manager not initialized")
    
    session = services.meet_session_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        services.meet_session_mgr.end_session(session_id)
        return {"status": "ended", "session_id": session_id}
    except Exception as e:
        logger.error(f"Failed to end session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}/snapshots")
@limiter.limit(RATE_LIMITS["get_snapshots"])
async def get_snapshot_info(request: Request, session_id: str):
    """Get snapshot count for a session"""
    services = get_services()
    
    if not services.meet_session_mgr:
        raise ServiceInitializationError("Session Manager", "Meet session manager unavailable")
    
    try:
        count = await services.meet_session_mgr.get_snapshot_count(session_id)
    except Exception as e:
        logger.error(f"Error getting snapshot count: {e}", exc_info=True)
        raise InterviewExecutionError(session_id, "snapshot_retrieval", str(e))
    
    return {"session_id": session_id, "snapshots": count}
