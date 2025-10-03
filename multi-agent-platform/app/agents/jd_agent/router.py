# app/agents/jd_agent/router.py

from fastapi import APIRouter, Depends
from .schema import JDInput
from .service import generate_job_description

# Import the service and dependency getter
from app.services.llm_service import LLMService
from app.core.dependencies import get_llm_service

# Create a router for this agent with a prefix
router = APIRouter(tags=["Job Description Agent"])

@router.post("/generate", summary="Generate a Job Description")
async def generate_jd(
    payload: JDInput,
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Accepts a job role, experience, and requirements to generate
    a complete job description using a predefined template.
    
    This endpoint is asynchronous and uses dependency injection for the LLM service.
    """
    # We now 'await' the result from the async service function
    # and pass the injected llm_service instance to it.
    jd_text = await generate_job_description(payload, llm_service)
    
    return {"job_role": payload.job_role, "job_description": jd_text}

@router.get("/health", summary="Health Check")
def health_check():
    """Returns a simple status to confirm the agent is running."""
    return {"status": "ok", "agent": "JD Agent"}