from fastapi import APIRouter, File, UploadFile, Form, Depends, HTTPException
import logging

from .schemas import ResumeMatchResponse
from .service import compare_jd_and_resume
from app.services.llm_service import LLMService
from app.agents.interview.utils.resume_parser import parse_resume
from app.core.dependencies import get_llm_service

router = APIRouter()
logger = logging.getLogger("resume_matcher")

@router.post("/match", response_model=ResumeMatchResponse, summary="Compare JD and Resume")
async def match_resume_to_jd(
    job_description: str = Form(..., description="The full text or JSON of the Job Description"),
    resume: UploadFile = File(..., description="The candidate's resume file (PDF, DOCX, TXT)"),
    llm_service: LLMService = Depends(get_llm_service)
):
    try:
        filename = resume.filename.lower() if resume.filename else ""
        file_format = None
        if filename.endswith(".pdf"):
            file_format = "pdf"
        elif filename.endswith(".docx"):
            file_format = "docx"
        elif filename.endswith(".txt"):
            file_format = "txt"
        
        # Read the file content
        resume_text = parse_resume(resume.file, file_format=file_format)
        
        if not resume_text:
            raise HTTPException(status_code=400, detail="Could not extract text from the uploaded resume file. Ensure it is a valid PDF, DOCX, or TXT.")

        match_result = await compare_jd_and_resume(job_description, resume_text, llm_service)
        
        return ResumeMatchResponse(
            candidate_name=match_result.get("candidate_name"),
            email=match_result.get("email"),
            contact=match_result.get("contact"),
            socials=match_result.get("socials", []),
            confidence_score=float(match_result.get("confidence_score", 0.0)),
            skills=match_result.get("skills", []),
            experience=match_result.get("experience"),
            strengths=match_result.get("strengths", []),
            weaknesses=match_result.get("weaknesses", [])
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Failed to match resume to JD: {e}")
        raise HTTPException(status_code=500, detail=str(e))
