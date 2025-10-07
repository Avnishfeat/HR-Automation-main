from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from .schema import CriteriaRequest, CriteriaResponse
from .service import generate_criteria
from app.services.llm_service import LLMService
from app.core.dependencies import get_llm_service

router = APIRouter(tags=["Candidate Criteria Agent"])

@router.post("/generate", summary="Generate Candidate Criteria from JD")
async def generate(
    payload: CriteriaRequest,
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Analyzes a Job Description (JD) and extracts structured search criteria
    for platforms like LinkedIn, Indeed, and Naukri.
    """
    try:
        result = await generate_criteria(payload, llm_service)
        # On success, return the data with a status: true field
        return {"status": True, "criteria": result}
        
    except HTTPException as e:
        # If a known error occurs, return a JSON response with status: false
        return JSONResponse(
            status_code=e.status_code,
            content={"status": False, "detail": e.detail}
        )
    except Exception:
        # For any other unexpected errors, return a generic 500 error
        return JSONResponse(
            status_code=500,
            content={"status": False, "detail": "An internal server error occurred."}
        )

@router.get("/health", summary="Health Check")
def health_check():
    """Returns a simple status to confirm the agent is running."""
    return {"status": "ok", "agent": "Criteria Agent"}
