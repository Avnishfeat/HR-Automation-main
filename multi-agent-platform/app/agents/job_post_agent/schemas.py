from pydantic import BaseModel, Field
from typing import Literal

class JobPostRequest(BaseModel):
    job_description: str = Field(
        ...,
        min_length=50,
        description="The full job description text."
    )
    platform: Literal['LinkedIn', 'Indeed', 'Naukri'] = Field(
        ...,
        description="The job site to generate a post for."
    )