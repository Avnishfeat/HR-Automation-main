from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
import logging

from .schema import ResumeAnalysisOutput
from .service import analyze_resume

# Import the service and dependency getter
from app.services.llm_service import LLMService
from app.core.dependencies import get_llm_service

logger = logging.getLogger("resume_score_agent")

# Create a router for this agent
router = APIRouter(tags=["Resume Analysis Agent"])


@router.post("/analyze", summary="Analyze Resume Against Job Description")
async def analyze_resume_endpoint(
    job_description: str = Form(..., description="Job description text"),
    resume_file: UploadFile = File(..., description="Resume file (.pdf, .docx, or .txt)"),
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Analyzes a candidate's resume against a job description.
    
    This endpoint accepts **multipart/form-data**:
    - **job_description**: The job description text
    - **resume_file**: The resume file (.pdf, .docx, or .txt)
    
    Returns a structure with status and detailed analysis (without echoing back the job description).
    """
    
    try:
        logger.info(f"Received analysis request for file: {resume_file.filename}")
        
        # Analyze the resume using the service
        analysis = await analyze_resume(
            job_description=job_description,
            resume_file=resume_file,
            llm_service=llm_service
        )
        
        # Return in the platform's standard format (without job_description)
        response_data = {
            "status": True,
            "analysis": analysis.model_dump()
        }
        
        return response_data
        
    except HTTPException as e:
        # If a known error occurs, return a JSON response with status: false
        logger.error(f"HTTP error during analysis: {e.detail}")
        return JSONResponse(
            status_code=e.status_code,
            content={"status": False, "detail": e.detail}
        )
    except Exception as e:
        # For any other unexpected errors, return a generic 500 error
        logger.error(f"Unexpected error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": False, "detail": "An internal server error occurred."}
        )


@router.get("/health", summary="Health Check")
def health_check():
    """Returns a simple status to confirm the agent is running."""
    return {"status": "ok", "agent": "Resume Analysis Agent"}