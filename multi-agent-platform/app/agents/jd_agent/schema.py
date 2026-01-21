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
    # Optional Inputs
    job_role: Optional[str] = Field(None, description="The job role (must be valid if provided).")
    requirements: str = Field(..., description="Key skills and requirements (Required).")
    preferred_skills: Optional[str] = Field(None, description="Preferred/Nice-to-have skills (generated if not provided).")
    
    # Other Optional Fields
    experience_range: Optional[str] = Field(None, description="Experience range.")
    salary_range: Optional[str] = Field(None, description="Salary range.")
    work_location: Optional[str] = Field(None, description="Work location.")
    job_type: Optional[str] = Field(None, description="Job type.")
    department: Optional[str] = Field(None, description="Department.")

    # Additional Form Fields
    jd_shift: Optional[str] = Field(None, description="Shift/Timing.")
    joining_timeline: Optional[str] = Field(None, description="Expected joining timeline.")
    travel_requirement: Optional[str] = Field(None, description="Travel requirements.")
    no_of_positions: Optional[str] = Field(None, description="Number of open positions.")
    total_budget: Optional[str] = Field(None, description="Budget.")
    
    # Administrative / Meta Fields
    employee_id: Optional[str] = Field(None, description="Requester ID")
    employee_name: Optional[str] = Field(None, description="Requester Name")
    employee_email_id: Optional[str] = Field(None, description="Requester Email")
    reports_to_id: Optional[str] = Field(None, description="Manager ID")
    reports_to_name: Optional[str] = Field(None, description="Manager Name")
    reports_to_email: Optional[str] = Field(None, description="Manager Email")
    job_code: Optional[str] = Field(None, description="Job Code")
    oprations: Optional[str] = Field(None, description="Operation")
    postion_open_date: Optional[str] = Field(None, description="Open Date")
    positionclosedate: Optional[str] = Field(None, description="Close Date")
    jd_validity_period: Optional[str] = Field(None, description="Validity Period")

    # ✅ Validation to ensure job_role is in ALLOWED_ROLES
    @field_validator("job_role")
    @classmethod
    def role_must_be_in_allowed_list(cls, value: str) -> str:
        if value and value not in ALLOWED_ROLES:
            raise ValueError(
                f"'{value}' is not a supported job role. "
                f"Please choose from: {', '.join(ALLOWED_ROLES)}"
            )
        return value
    
    def as_prompt_snippet(self) -> str:
        """Helper to format ALL input fields for the LLM prompt, grouped by Section."""
        return f"""
        # Section: Requester/Recruiter Details
        Requester ID: {self.employee_id or 'Not specified'}
        Requester Name: {self.employee_name or 'Not specified'}
        Requester Email: {self.employee_email_id or 'Not specified'}
        Reporting Manager Code: {self.reports_to_id or 'Not specified'}
        Reporting Manager Name: {self.reports_to_name or 'Not specified'}
        Reporting Manager Email: {self.reports_to_email or 'Not specified'}

        # Section: Basic Job Details
        Job Code (auto-gen): {self.job_code or 'Not specified'}
        Job Title: {self.job_role or 'Not specified'} 
        Number of Positions: {self.no_of_positions or 'Not specified'}
        Operation: {self.oprations or 'INSERT'}
        Department: {self.department or 'Not specified'}
        Job Type: {self.job_type or 'Not specified'}
        Work Location: {self.work_location or 'Not specified'}
        Shift/Timing: {self.jd_shift or 'Not specified'}
        Total Budget: {self.total_budget or 'Not specified'}
        Position Open Date: {self.postion_open_date or 'Not specified'}
        Position Close Date: {self.positionclosedate or 'Not specified'}
        JD Validity Period: {self.jd_validity_period or 'Not specified'}
        Experience Range (Years): {self.experience_range or 'Not specified'}
        Salary Range (Lakhs): {self.salary_range or 'Not specified'}
        Joining Timeline: {self.joining_timeline or 'Not specified'}
        Travel Requirement: {self.travel_requirement or 'Not specified'}

        # Section: Role Description
        Required Skills: {self.requirements or 'Not specified'}
        Preferred Skills: {self.preferred_skills if hasattr(self, 'preferred_skills') else 'Not specified'} 
        Overview: {self.overview if hasattr(self, 'overview') else 'Not specified'}
        Key Responsibilities: {self.key_responsibilities if hasattr(self, 'key_responsibilities') else 'Not specified'}
        """

    class Config:
        str_strip_whitespace = True 
        json_schema_extra = {
            "example": {
                "job_role": "Data Analyst",
                "experience_range": "5+ years of experience in data analysis",
                "requirements": "Proficiency in SQL, experience with Power BI, and knowledge of Python for data manipulation.",
            }
        }
