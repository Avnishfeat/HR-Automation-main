from fastapi import APIRouter, HTTPException
from .schemas import JobRequest, TalentMatchApiResponse
from .service import TalentMatcherService

router = APIRouter(tags=["Talent Matcher"])
service = TalentMatcherService()

@router.post("/match-job", response_model=TalentMatchApiResponse, summary="Match Employees to Job Description")
async def match_job(request: JobRequest):
    """
    Receives a job description (from JD Agent output), finds matching employee profiles, 
    and returns them wrapped in a standardized API response.
    
    The job_description field should contain the structured output from the JD Agent.
    Optionally, you can override the degree and experience requirements.
    """
    try:
        # Call the matching service to get a list of matched employees
        matched_employees = service.match(request)
        
        # Return the successful response structure
        return {
            "status": True, 
            "data": matched_employees,
            "message": f"Found {len(matched_employees)} matching candidates for {request.job_role}"
        }

    except Exception as e:
        # Log the error for debugging
        import logging
        logger = logging.getLogger("talent_matcher")
        logger.error(f"Error during job matching: {e}", exc_info=True)
        
        # Return a 500 error with details
        raise HTTPException(
            status_code=500,
            detail={
                "status": False, 
                "data": [], 
                "error": f"An internal server error occurred: {str(e)}"
            }
        )

@router.get("/health", summary="Health Check")
def health_check():
    """Returns a simple status to confirm the talent matcher is running."""
    return {"status": "ok", "agent": "Talent Matcher"}