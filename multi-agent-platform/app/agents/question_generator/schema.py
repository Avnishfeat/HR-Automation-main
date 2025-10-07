# File: app/agents/question_generator/schemas.py

from pydantic import BaseModel, Field
from typing import List

class QuestionnaireRequest(BaseModel):
    """
    Defines the three inputs needed to generate a questionnaire.
    """
    jd_text: str = Field(
        ...,
        description="The full text of the job description."
    )
    requirements: List[str] = Field(
        ...,
        min_length=1,
        description="A list of specific job requirements like skills or qualifications."
    )
    resume_text: str = Field(
        ...,
        description="The full text extracted from the candidate's resume."
    )

class QuestionnaireResponse(BaseModel):
    status: bool = Field(True, description="Indicates if the request was successful.")
    questions: List[str]

class ErrorResponse(BaseModel):
    status: bool = Field(False, description="Indicates that the request failed.")
    detail: str = Field(..., description="A description of the error that occurred.")