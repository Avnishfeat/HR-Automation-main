from fastapi import APIRouter, Depends
from .schema import CriteriaRequest, CriteriaResponse
from .service import generate_criteria
from app.services.llm_service import LLMService
from app.core.dependencies import get_llm_service

router = APIRouter(tags=["Candidate Criteria Agent"])

@router.post("/generate", response_model=CriteriaResponse, summary="Generate Candidate Criteria from JD")
async def generate(
    payload: CriteriaRequest,
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Analyzes a Job Description (JD) and extracts structured search criteria
    for platforms like LinkedIn, Indeed, and Naukri.
    """
    result = await generate_criteria(payload, llm_service)
    return {"criteria": result}

@router.get("/health", summary="Health Check")
def health_check():
    """Returns a simple status to confirm the agent is running."""
    return {"status": "ok", "agent": "Criteria Agent"}