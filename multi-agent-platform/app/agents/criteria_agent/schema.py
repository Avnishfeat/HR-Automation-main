# app/agents/criteria_agent/schema.py

from pydantic import BaseModel, Field
from typing import Literal, Dict, Any

class CriteriaRequest(BaseModel):
    """Input model for generating candidate search criteria."""
    jd_text: str = Field(..., min_length=50, description="The full text of the Job Description.")
    target: Literal["linkedin", "indeed", "naukri", "all"] = Field(..., description="The target platform(s) for the criteria.")

    class Config:
        json_schema_extra = {
            "example": {
                "jd_text": "We are hiring a Senior Data Analyst in Mumbai. The ideal candidate has 5+ years of experience with SQL, Python, and Power BI. Responsibilities include creating dashboards and performing statistical analysis.",
                "target": "all"
            }
        }

class CriteriaResponse(BaseModel):
    """Output model for the generated criteria."""
    criteria: Dict[str, Any]