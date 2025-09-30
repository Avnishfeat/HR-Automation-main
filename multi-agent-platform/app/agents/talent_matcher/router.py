from fastapi import APIRouter
from .schemas import JobRequest, MatchResponse
from .service import TalentMatcherService

router = APIRouter()
service = TalentMatcherService()

@router.post("/match-job", response_model=list[MatchResponse])
async def match_job(request: JobRequest):
    return service.match(request)
