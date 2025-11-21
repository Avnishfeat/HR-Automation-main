# app/agents/criteria_agent/schema.py

from pydantic import BaseModel, Field, field_validator
from typing import Literal, Dict, Any

def _flatten_jd_object_to_string(jd_data: Dict[str, Any]) -> str:
    """
    Converts the structured JD object into a single flat string that
    the LLM can easily parse.
    """
    parts = []
    
    if "job_role" in jd_data:
        parts.append(f"Job Role: {jd_data['job_role']}")
        
    if "job_description" in jd_data and isinstance(jd_data['job_description'], dict):
        jd_desc = jd_data['job_description']
        
        # Define a specific order for flattening to ensure logical flow
        key_order = [
            "overview", 
            "key_responsibilities", 
            "required_skills",
            "preferred_skills", 
            "minimum_qualification", 
            "key_skills_and_qualifications", 
            "desired_attributes",
            "languages", 
            "benefits"
        ]
        
        for key in key_order:
            if key in jd_desc and jd_desc[key]:
                # Format key: "key_responsibilities" -> "Key Responsibilities"
                formatted_key = key.replace('_', ' ').title()
                parts.append(f"{formatted_key}: {jd_desc[key]}")

    return "\n\n".join(parts)


class CriteriaRequest(BaseModel):
    """Input model for generating candidate search criteria."""
    jd_text: str = Field(..., min_length=50, description="The full text of the Job Description (can be a string or a structured JSON object).")
    target: Literal["linkedin", "indeed", "naukri", "all"] = Field(..., description="The target platform(s) for the criteria.")

    @field_validator("jd_text", mode="before")
    @classmethod
    def flatten_jd_if_object(cls, v: Any) -> str:
        """
        This validator runs before Pydantic's main validation.
        It checks if jd_text is a dictionary. If so, it flattens it
        into a string. If it's already a string, it does nothing.
        """
        if isinstance(v, dict):
            # If input is a dictionary, flatten it
            return _flatten_jd_object_to_string(v)
        if isinstance(v, str):
            # If input is already a string, just return it
            return v
        # Otherwise, let Pydantic raise the validation error
        raise ValueError("jd_text must be a string or a valid JD JSON object")

    class Config:
        json_schema_extra = {
            "example": {
                "jd_text": {
                    "job_role": "AI/ML Engineer",
                    "job_description": {
                        "required_skills": "Strong foundation in Python programming, core machine learning concepts, and data analysis techniques.",
                        "preferred_skills": "Familiarity with deep learning frameworks such as TensorFlow or PyTorch.",
                        "minimum_qualification": "Bachelor's degree in Computer Science...",
                        "overview": "We are seeking a highly motivated AI/ML Engineer...",
                        "key_responsibilities": "Assist in the design, development..."
                    }
                },
                "target": "all"
            }
        }

class CriteriaResponse(BaseModel):
    """Output model for the generated criteria."""
    criteria: Dict[str, Any]