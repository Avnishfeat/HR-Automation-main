# File: app/agents/question_generator/router.py

from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import List

# Local Imports
from .service import QuestionGenerationService
from .schema import QuestionnaireResponse, ErrorResponse

# Shared Application Imports
from app.core.dependencies import get_llm_service
from app.services.llm_service import LLMService

router = APIRouter()

def get_question_generation_service(llm_service: LLMService = Depends(get_llm_service)):
    return QuestionGenerationService(llm_service=llm_service)

@router.post(
    "/generate",
    response_model=QuestionnaireResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"}
    }
)
async def generate_questionnaire_from_file_endpoint(
    jd_text: str = Form(..., description="The full text of the job description."),
    requirements: List[str] = Form(..., description="A list of specific job requirements."),
    resume_file: UploadFile = File(..., description="The candidate's resume in PDF format."),
    qg_service: QuestionGenerationService = Depends(get_question_generation_service),
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Accepts a job description, requirements, and a resume file, uploads the file
    to the Gemini File API, and generates a questionnaire.
    """
    if resume_file.content_type != "application/pdf":
        # --- CHANGE APPLIED HERE ---
        return JSONResponse(
            status_code=400,
            content={"status": False, "detail": "Invalid file type. Please upload a PDF."}
        )
    try:
        resume_bytes = await resume_file.read()
        
        uploaded_resume_file = await llm_service.upload_file(
            file_bytes=resume_bytes,
            display_name=resume_file.filename
        )
        
        questions = await qg_service.generate_questionnaire(
            jd_text=jd_text,
            requirements=requirements,
            resume_file=uploaded_resume_file
        )
        
        return QuestionnaireResponse(status=True, questions=questions)
        
    except ValueError as e:
        # --- CHANGE APPLIED HERE ---
        return JSONResponse(
            status_code=400,
            content={"status": False, "detail": str(e)}
        )
    except Exception as e:
        # --- CHANGE APPLIED HERE ---
        return JSONResponse(
            status_code=500,
            content={"status": False, "detail": f"An unexpected error occurred: {e}"}
        )