from pydantic import BaseModel, Field
from typing import List, Optional

class ResumeMatchResponse(BaseModel):
    candidate_name: Optional[str] = Field(None, description="The name of the candidate extracted from the resume.")
    email: Optional[str] = Field(None, description="The email address of the candidate.")
    contact: Optional[str] = Field(None, description="The contact number of the candidate.")
    socials: List[str] = Field(default_factory=list, description="Links to the candidate's social profiles (e.g., LinkedIn, GitHub).")
    confidence_score: float = Field(..., description="A score between 0.0 and 1.0 representing the match confidence.")
    skills: List[str] = Field(default_factory=list, description="Skills extracted from the resume.")
    experience: Optional[str] = Field(None, description="A summary of the candidate's relevant experience.")
    strengths: List[str] = Field(..., description="A list of the candidate's strengths relative to the JD.")
    weaknesses: List[str] = Field(..., description="A list of the candidate's weaknesses relative to the JD.")
