from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any
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
    
    Returns a structure compatible with Talent Matcher Agent.
    """
    try:
        jd_json = await generate_job_description(payload, llm_service)
        
        # Return in format compatible with Talent Matcher
        # Structure: { status, job_role, job_description: {...} }
        response_data = {
            "status": True,
            "job_role": payload.job_role,
            "job_description": jd_json  # Nested structure for Talent Matcher
        }
        return response_data

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


@router.post("/generate-flat", summary="Generate JD (Flat Structure)")
async def generate_jd_flat(
    payload: JDInput,
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Alternative endpoint that returns flat structure (original format).
    Use /generate for Talent Matcher compatibility.
    """
    try:
        jd_json = await generate_job_description(payload, llm_service)
        
        # Flat structure: all fields at root level
        response_data = {"status": True, **jd_json}
        return response_data

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": False, "detail": e.detail}
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"status": False, "detail": "An internal server error occurred."}
        )


@router.get("/health", summary="Health Check")
def health_check():
    """Returns a simple status to confirm the agent is running."""
    return {"status": "ok", "agent": "JD Agent"}