from pydantic import BaseModel
from typing import List

class JobRequest(BaseModel):
    """Schema for the incoming job matching request."""
    job_description: str
    required_degree: str
    min_years_experience: int

class MatchResponse(BaseModel):
    """Schema for a single employee match."""
    employee_id: str
    score: float
    reasons: List[str]

    class Config:
        from_attributes = True

class TalentMatchApiResponse(BaseModel):
    """The final, wrapped API response schema."""
    status: bool
    data: List[MatchResponse]