from fastapi import APIRouter, HTTPException, Depends
from .schemas import JobRequest, TalentMatchApiResponse, MatchResponse
from .service import TalentMatcherService
import logging

router = APIRouter(tags=["Talent Matcher"])
logger = logging.getLogger("talent_matcher")

# --- START OF THE FIX ---
# Cache the service instance (singleton)
_talent_matcher_service_instance = None

def get_talent_matcher_service():
    """Dependency injector to get a singleton instance of the service."""
    global _talent_matcher_service_instance
    if _talent_matcher_service_instance is None:
        logger.info("Initializing TalentMatcherService...")
        _talent_matcher_service_instance = TalentMatcherService()
    return _talent_matcher_service_instance
# --- END OF THE FIX ---


@router.post("/match-job", response_model=TalentMatchApiResponse, summary="Match Employees to Job Description")
async def match_job(
    request: JobRequest,
    # The service is now injected by FastAPI:
    service: TalentMatcherService = Depends(get_talent_matcher_service)
):
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

    except HTTPException as e:
        # Re-raise HTTPExceptions directly
        raise e
        
    except Exception as e:
        # Log the error for debugging
        logger.error(f"Error during job matching: {e}", exc_info=True)
        
        # Return a 500 error with details
        # NOTE: The original router returned a 500 error with a 200 OK status code,
        # which is incorrect. This raises a proper 500.
        raise HTTPException(
            status_code=500,
            detail=f"An internal server error occurred: {str(e)}"
            # Returning a full dict in detail is non-standard.
            # We will test for this specific string.
        )

@router.get("/health", summary="Health Check")
def health_check():
    """Returns a simple status to confirm the talent matcher is running."""
    return {"status": "ok", "agent": "Talent Matcher"}