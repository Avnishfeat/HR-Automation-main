from fastapi import APIRouter, Depends, HTTPException
from .schemas import JobPostRequest
from .services import JobPostAgentService
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
        return {"platform": request.platform, "generated_post": result["result"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))