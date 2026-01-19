from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List, Dict, Any
from enum import Enum

class VideoCaptureMethod(str, Enum):
    JAVASCRIPT = "javascript"
    SCREENSHOT = "screenshot"

class StartInterviewRequest(BaseModel):
    candidate_id: str = Field(..., description="Unique identifier for the candidate")
    job_role: str = Field(..., description="Target job role")
    meet_link: Optional[str] = Field(None, description="Google Meet link (optional, will generate if missing)")
    resume_text: Optional[str] = Field(None, description="Parsed text content of the resume")
    job_description: Optional[str] = Field(None, description="Job description text")
    questionnaire: Optional[List[str]] = Field(default_factory=list, description="List of pre-screening questions")
    
    # Configuration
    enable_video: bool = Field(True, description="Enable video capture and analysis")
    video_capture_method: VideoCaptureMethod = Field(VideoCaptureMethod.JAVASCRIPT, description="Method for capturing video frames")
    audio_device_index: Optional[int] = Field(None, description="Specific audio device index for bot audio input")

class InterviewStatusResponse(BaseModel):
    session_id: str
    status: str
    candidate_id: str
    meet_link: Optional[str]
    snapshot_count: int
    created_at: Optional[str]
    message: Optional[str] = None
