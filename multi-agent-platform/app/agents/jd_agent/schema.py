# app/agents/jd_agent/schema.py

from typing import Optional, List
# Import field_validator for the modern Pydantic V2 approach
from pydantic import BaseModel, Field, field_validator

# ✅ Single source of truth for all supported job roles.
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

    # ✅ Newly added roles (from your request)
    "Inside Sales Associate": "Inside_Sales_Associate.txt",
    "Junior RPA Trainee": "Junior_RPA_Trainee.txt",
    "Presales Consultant (IT Industry)": "Presales_Consultant_IT_Industry.txt",
    "Sales Account Manager": "Sales_Account_Manager.txt",
    "SAP Consultant": "SAP_Consultant.txt",
    "Business Analyst - IT Industry - Mumbai": "Business_Analyst_IT_Mumbai.txt",
    "Business Analyst - IT Industry - Pune": "Business_Analyst_IT_Pune.txt",
    "Tech Support - IT Specialist": "Tech_Support_IT_Specialist.txt",
    "Technical Trainer": "Technical_Trainer.txt",
    "UPI Reconciliation Specialist (IT Industry)": "UPI_Reconciliation_Specialist_IT.txt",
    "Inside Sales Executive": "Inside_Sales_Executive.txt",
    "Senior Business Analyst": "Senior_Business_Analyst.txt",
    "Financial Architect SAP FICA": "Financial_Architect_SAP_FICA.txt",
    "SDE 1 - Fullstack Developer": "SDE1_Fullstack_Developer.txt",
    "SDE 2 - Fullstack Developer": "SDE2_Fullstack_Developer.txt",
    "SDE 3 - Fullstack Developer": "SDE3_Fullstack_Developer.txt",
    "SAP Technical developer": "SAP_Technical_Developer.txt",
    "HR Recruiter": "HR_Recruiter.txt",
    "Chief Partnership Officer (CPO) - IT Industry": "Chief_Partnership_Officer_IT.txt",
    "Senior RPA Developer": "Senior_RPA_Developer.txt",
    "Senior Software Developer": "Senior_Software_Developer.txt",
    "Junior Business Analyst": "Junior_Business_Analyst.txt",
    "L1 RPA Support Engineer": "L1_RPA_Support_Engineer.txt",
    "Node JS/ Actionabl Developer": "NodeJS_Actionabl_Developer.txt",
    "HR Admin cum Executive": "HR_Admin_Executive.txt",
    "Global Pre-Sales Director": "Global_PreSales_Director.txt",
    "Business Development Manager": "Business_Development_Manager.txt",
}

# ✅ Dynamically create allowed roles from the map
ALLOWED_ROLES: List[str] = list(ROLE_FILE_MAP.keys())


class JDInput(BaseModel):
    """Pydantic model for Job Description generation input."""
    job_role: str = Field(..., description="The job role, must be one of the allowed roles.")
    experience: Optional[str] = Field(None, example="3-5 years", description="Required experience level.")
    requirements: Optional[str] = Field(None, example="SQL, Python, Power BI", description="Key skills and requirements.")

    # ✅ Validation to ensure job_role is in ALLOWED_ROLES
    @field_validator("job_role")
    @classmethod
    def role_must_be_in_allowed_list(cls, value: str) -> str:
        if value not in ALLOWED_ROLES:
            raise ValueError(
                f"'{value}' is not a supported job role. "
                f"Please choose from: {', '.join(ALLOWED_ROLES)}"
            )
        return value
    
    def as_prompt_snippet(self) -> str:
        """Helper to format the experience and requirements for LLM prompt."""
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
