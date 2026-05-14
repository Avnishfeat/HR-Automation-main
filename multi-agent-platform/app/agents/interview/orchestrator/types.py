# app/orchestrator/types.py
from typing import NamedTuple, Optional, Set, Any # <--- Added Set, Any
from datetime import datetime
from pathlib import Path
import threading
from enum import Enum
from pydantic import BaseModel, Field

class InterviewPhase(str, Enum):
    INITIALIZING = "initializing"
    GREETING = "greeting"
    INTRODUCTION = "introduction"
    INTERVIEW_LOOP = "interview_loop"
    CONCLUSION = "conclusion"
    COMPLETED = "completed"

class InterviewState(BaseModel):
    """
    Persistent state object. 
    Single Source of Truth for the interview progress.
    """
    session_id: str
    phase: InterviewPhase = InterviewPhase.INITIALIZING
    turn_count: int = 1
    questions_asked_count: int = 0
    start_time: float = Field(default_factory=lambda: datetime.now().timestamp())
    current_question_text: Optional[str] = None
    last_user_transcript: Optional[str] = None
    exit_confirmation_pending: bool = False
    is_resumed: bool = False
    consecutive_error_count: int = 0
    total_error_count: int = 0

class InterviewSession(NamedTuple):
    """Holds runtime objects that cannot be serialized to DB."""
    session_id: str
    meet: Any 
    stop_event: threading.Event
    #  NEW FIELD: Linked set for real-time flag monitoring
    malpractice_flags: Set[str] 

class ResponseData(NamedTuple):
    """Encapsulates a candidate's response."""
    transcript: str
    audio_path: Path
    start_time: Optional[datetime]
    end_time: datetime
    turn_count: int
    is_follow_up: bool = False

class HandlerResult(NamedTuple):
    """Result of response evaluation and handling."""
    final_response: ResponseData
    proceed: bool
