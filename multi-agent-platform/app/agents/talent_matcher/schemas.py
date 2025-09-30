from pydantic import BaseModel
from typing import List

class JobRequest(BaseModel):
    job_description: str
    required_degree: str
    min_years_experience: int

class MatchResponse(BaseModel):
    employee_id: str
    score: float
    reasons: List[str]
