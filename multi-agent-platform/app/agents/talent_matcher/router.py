from fastapi import APIRouter, HTTPException
from .schemas import JobRequest, TalentMatchApiResponse
from .service import TalentMatcherService

router = APIRouter()
service = TalentMatcherService()

@router.post("/match-job", response_model=TalentMatchApiResponse)
async def match_job(request: JobRequest):
    """
    Receives a job request, finds matching employee profiles, 
    and returns them wrapped in a standardized API response.
    """
    try:
        # Call the matching service to get a list of matched employees
        matched_employees = service.match(request)
        
        # Return the successful response structure
        return {"status": True, "data": matched_employees}

    except Exception as e:
        # If any error occurs during the process, return a 500 error
        # with a status of false. It's good practice to log the error `e` here.
        # logger.error(f"Error during job matching: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": False, "data": [], "error": "An internal server error occurred."}
        )