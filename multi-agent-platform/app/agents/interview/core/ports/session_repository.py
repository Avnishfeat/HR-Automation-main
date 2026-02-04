from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime

class SessionRepository(ABC):
    """
    Abstract Interface for Database Operations.
    The Core layer depends on this, not on Mongo directly.
    """
    # --- File Storage ---
    @abstractmethod
    def save_file(self, filename: str, data: bytes, content_type: str = "audio/wav") -> bool:
        pass

    @abstractmethod
    def get_file(self, filename: str) -> Optional[bytes]:
        pass

    @abstractmethod
    def list_files(self, prefix: str) -> List[str]:
        """List files starting with prefix."""
        pass

    # --- Session Management ---
    @abstractmethod
    def create_session(self, resume_text: str, candidate_id: str, job_role: str, questionnaire: List[str], job_description: Optional[str] = None) -> str:
        pass

    @abstractmethod
    def add_message_to_session(self, session_id: str, role: str, text: str, audio_path: Optional[str] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None, is_follow_up: bool = False, turn_count: int = 0) -> None:
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_full_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def update_session_status(self, session_id: str, status: str):
        pass

    # --- Checkpoints & Analysis ---
    @abstractmethod
    def save_checkpoint(self, session_id: str, state_data: Dict[str, Any]):
        pass

    @abstractmethod
    def load_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_analysis_result(self, session_id: str, analysis_data: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    def get_analysis_report(self, session_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_transcript_text(self, session_id: str) -> Optional[str]:
        pass

    # --- Usage Tracking ---
    @abstractmethod
    def update_gemini_token_usage(self, session_id: str, usage_type: str, p: int, r: int, t: int):
        pass

    @abstractmethod
    def update_tts_character_usage(self, session_id: str, count: int):
        pass

    @abstractmethod
    def update_stt_usage(self, session_id: str, seconds: float):
        pass
    
    @abstractmethod
    def check_connection(self) -> bool:
        pass