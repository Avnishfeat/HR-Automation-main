# app/agents/jd_agent/schema.py

from typing import Optional, List
# Import field_validator for the modern Pydantic V2 approach
from pydantic import BaseModel, Field, field_validator

# This dictionary is the single source of truth for all supported job roles.
ROLE_FILE_MAP = {
    "Software Developer / Engineer": "Software_Developer_Engineer.txt",
    "Web Developer": "Web_Developer.txt",
    "Mobile App Developer": "Mobile_App_Developer.txt",
    "Cloud Engineer (AWS/Azure/GCP)": "Cloud_Engineer_AWS_Azure_GCP.txt",
    "Network Engineer": "Network_Engineer.txt",
    "Data Analyst": "Data_Analyst.txt",
    "Business Analyst": "Business_Analyst.txt",
    "Data Scientist": "Data_Scientist.txt",
    "Machine Learning Engineer": "Machine_Learning_Engineer.txt",
    "AI/ML Engineer": "AI_ML_Engineer.txt",
    "RPA Developer": "RPA_Developer.txt",
    "Marketing Manager": "Marketing_Manager.txt",
    "Technical Engineer": "Technical_Engineer.txt",
}

# Dynamically create the list of allowed roles from the keys of the map
ALLOWED_ROLES: List[str] = list(ROLE_FILE_MAP.keys())


class JDInput(BaseModel):
    """Pydantic model for Job Description generation input."""
    job_role: str = Field(..., description="The job role, must be one of the allowed roles.")
    experience: Optional[str] = Field(None, example="3-5 years", description="Required experience level.")
    requirements: Optional[str] = Field(None, example="SQL, Python, Power BI", description="Key skills and requirements.")

    # ✅ BEST PRACTICE: Use the modern @field_validator decorator
    @field_validator("job_role")
    @classmethod
    def role_must_be_in_allowed_list(cls, value: str) -> str:
        """Validate that the job_role is one of the supported roles."""
        if value not in ALLOWED_ROLES:
            raise ValueError(f"'{value}' is not a supported job role. Please choose from: {', '.join(ALLOWED_ROLES)}")
        return value
    
    def as_prompt_snippet(self) -> str:
        """Helper to format the experience and requirements for the main prompt."""
        return f"Experience: {self.experience or 'Not specified'}\nRequirements: {self.requirements or 'Not specified'}"

    class Config:
        str_strip_whitespace = True 
        json_schema_extra = {
            "example": {
                "job_role": "Data Analyst",
                "experience": "5+ years of experience in data analysis",
                "requirements": "Proficiency in SQL, experience with Power BI, and knowledge of Python for data manipulation.",
            }
        }