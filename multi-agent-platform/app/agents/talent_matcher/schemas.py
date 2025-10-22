from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union, Dict, Any

class JobDescriptionDetail(BaseModel):
    """Schema for the detailed job description structure from JD Agent."""
    required_skills: str
    preferred_skills: str
    minimum_qualification: str
    languages: str
    overview: str
    key_responsibilities: str
    key_skills_and_qualifications: str
    desired_attributes: str
    benefits: str

class JobRequest(BaseModel):
    """Schema for the incoming job matching request - accepts JD Agent output in multiple formats."""
    job_role: str = Field(..., description="The job role title")
    job_description: Union[JobDescriptionDetail, Dict[str, Any]] = Field(..., description="Detailed job description from JD Agent")
    
    # Optional overrides if you want to customize matching criteria
    required_degree: Optional[str] = Field(None, description="Override degree requirement (extracted from job_description if not provided)")
    min_years_experience: Optional[int] = Field(None, description="Override minimum years (extracted from job_description if not provided)")
    
    @field_validator("job_description", mode="before")
    @classmethod
    def normalize_job_description(cls, value):
        """
        Normalizes job_description to JobDescriptionDetail object.
        Handles both nested and flat structures from JD Agent.
        """
        if isinstance(value, dict):
            # If it's a dict, ensure it has the required fields
            return JobDescriptionDetail(**value)
        return value

class MatchResponse(BaseModel):
    """Schema for a single employee match."""
    employee_id: str
    name: str
    title: str
    score: float
    experience_years: int
    reasons: List[str]

    class Config:
        from_attributes = True

class TalentMatchApiResponse(BaseModel):
    """The final, wrapped API response schema."""
    status: bool
    data: List[MatchResponse]
    message: Optional[str] = None