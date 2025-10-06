from fastapi import APIRouter, Depends, HTTPException
from .schemas import JobPostRequest
from .service import JobPostAgentService
from app.core.dependencies import get_llm_service

router = APIRouter(prefix="/job-post-agent", tags=["Job Post Agent"])

@router.post("/generate")
async def generate_job_post(
    request: JobPostRequest,
    llm_service = Depends(get_llm_service)
):
    try:
        service = JobPostAgentService(llm_service)
        result = await service.generate_post(
            platform=request.platform,
            job_description=request.job_description
        )
        
        # --- ADD 'status: True' TO THE SUCCESSFUL RESPONSE ---
        return {
            "status": True,
            "platform": request.platform,
            "generated_post": result["result"]
        }
        
    except Exception as e:
        # --- MODIFY THE ERROR RESPONSE TO INCLUDE 'status: False' ---
        raise HTTPException(
            status_code=500, 
            detail={"status": False, "error": str(e)}
        )