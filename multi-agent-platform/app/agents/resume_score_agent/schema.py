from pydantic import BaseModel, Field
from typing import List, Optional

class AnalysisResponse(BaseModel):
    """
    The structured response from the comprehensive resume analysis.
    """
    match_score: float = Field(
        ..., 
        ge=0, 
        le=100, 
        description="Overall match score (0-100) based on experience, projects, and skills alignment"
    )
    
    is_eligible: bool = Field(
        ..., 
        description="Whether the candidate should be considered for an interview"
    )
    
    justification: str = Field(
        ..., 
        description="Comprehensive evaluation covering: years of experience, relevant projects, skill proficiency, strengths, and overall fit for the role"
    )
    
    missing_keywords: List[str] = Field(
        default_factory=list, 
        description="Critical skills, technologies, or qualifications from the JD that are missing or not demonstrated in the resume"
    )
    
    experience_years: float = Field(
        ...,
        ge=0,
        description="Total years of RELEVANT, PROFESSIONAL experience (excluding internships)"
    )
    
    project_count: int = Field(
        ...,
        ge=0,
        description="Number of relevant projects identified ONLY from a dedicated 'Projects' section"
    )
    
    key_strengths: List[str] = Field(
        ...,
        min_length=1,
        description="Candidate's standout strengths for this specific role (at least 1 required)"
    )
    
    internship_count: int = Field(
        ...,
        ge=0,
        description="Total number of distinct internships listed (e.g., 'Virtual Internship')"
    )

class ResumeAnalysisOutput(BaseModel):
    """Output model matching the platform pattern"""
    status: bool
    analysis: AnalysisResponse
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": True,
                "analysis": {
                    "match_score": 75.5,
                    "is_eligible": True,
                    "justification": "Candidate has 4 years of relevant experience...",
                    "missing_keywords": ["AWS", "Docker"],
                    "experience_years": 4.0,
                    "project_count": 3,
                    "key_strengths": ["Strong Python skills", "Full-stack experience"],
                    "internship_count": 1
                }
            }
        }