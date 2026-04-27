# app/services/transcript_manager.py
import logging
from datetime import datetime
from typing import Optional, Dict
import threading

from app.agents.interview.core.ports.session_repository import SessionRepository

logger = logging.getLogger(__name__)

class TranscriptManager:
    """
    Manages all transcript-related operations, relying PURELY on MongoDB
    for storage and state. No local files.
    """
    
    def __init__(self, db_handler: SessionRepository):
        self.db = db_handler
        self._latest_transcript_for_gemini: Dict[str, Optional[str]] = {}
        self._transcript_lock = threading.Lock()

    def initialize_transcript_state(self, session_id: str):
        with self._transcript_lock:
            self._latest_transcript_for_gemini[session_id] = "[Candidate introduction pending]"
        logger.debug(f"TranscriptManager: Initialized state for {session_id}")

    def get_latest_transcript(self, session_id: str) -> str:
        with self._transcript_lock:
            transcript = self._latest_transcript_for_gemini.get(session_id, "[Silence]")
        return transcript if transcript else "[Silence]"

    def _update_transcript_immediate(self, session_id: str, transcript: str) -> None:
        with self._transcript_lock:
            if transcript and not transcript.startswith("[Error") and transcript != "[Unintelligible]" and transcript.strip() != "[No response]":
                self._latest_transcript_for_gemini[session_id] = transcript

    def update_pending_transcript(self, session_id: str, interim_text: str) -> None:
        """Update with interim transcript (user still speaking).
        
        This allows Gemini to see partial input early, reducing response latency.
        The interim text is prefixed with [Speaking...] to indicate it's incomplete.
        """
        with self._transcript_lock:
            if interim_text and len(interim_text) > 5:  # Ignore very short fragments
                self._latest_transcript_for_gemini[session_id] = f"[Speaking...] {interim_text}"

    def process_and_log_transcript(
        self, 
        session_id: str, 
        audio_path: str,
        transcript: str, 
        turn_count: int,
        candidate_id: str, 
        start_time: Optional[datetime], 
        end_time: Optional[datetime],
        is_follow_up_response: bool = False
    ) -> None:
        try:
            logger.info(f"(BG Thread) Logging user transcript (Turn {turn_count}): {transcript}")
            
            # 1. Log to MongoDB (Structured Data)
            self.db.add_message_to_session(
                session_id, "user", transcript, audio_path, 
                start_time, end_time, 
                is_follow_up=is_follow_up_response,
                turn_count=turn_count
            )
            
            # 2. Update In-Memory State for next question generation
            with self._transcript_lock:
                if transcript and not transcript.startswith("[Error") and transcript != "[Unintelligible]" and transcript.strip() != "[No response]":
                    self._latest_transcript_for_gemini[session_id] = transcript
                    logger.info(f"(BG Thread) Updated in-memory transcript for {session_id}")
                    
        except Exception as e:
            logger.error(f"(BG Thread) Error in process_and_log_transcript: {e}", exc_info=True)

    def save_final_transcript_to_db(self, session_id: str) -> bool:
        """
        Generates the final formatted transcript string and saves it 
        to the MongoDB session document (instead of a local file).
        """
        try:
            session_data = self.db.get_full_session(session_id)
            if not session_data: 
                logger.error(f"TranscriptManager: No session data found for {session_id}")
                return False
            
            # Build the readable string
            lines = []
            lines.append(f"--- Interview Transcript ---")
            lines.append(f"Session ID: {session_id}")
            lines.append(f"Candidate ID: {session_data.get('candidate_id', 'unknown')}")
            
            created_at = session_data.get('created_at')
            if created_at:
                lines.append(f"Date: {created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            
            usage = session_data.get("usage_tracking", {})
            stt = usage.get("stt", {})
            lines.append(f"STT Duration: {stt.get('total_seconds', 0.0):.2f}s")
            lines.append("--------------------------------\n")

            # Append Conversation
            for msg in session_data.get("conversation", []):
                role = msg.get("role", "unknown").capitalize()
                text = msg.get("text", "")
                turn = msg.get("turn", "?")
                ts = msg.get("timestamp")
                ts_str = ts.strftime('%H:%M:%S') if ts else "N/A"
                
                lines.append(f"[{ts_str}] (Turn {turn}) {role}:\n{text}\n")
            
            full_text = "\n".join(lines)
            
            # Save to DB
            success = self.db.save_transcript_text(session_id, full_text)
            if success:
                logger.info(f"TranscriptManager: Saved formatted transcript to MongoDB for {session_id}")
                return True
            else:
                logger.error(f"TranscriptManager: Failed to save text to MongoDB")
                return False
                
        except Exception as e: 
            logger.error(f"TranscriptManager: Generation failed: {e}", exc_info=True)
            return False

    def clear_session_state(self, session_id: str):
        with self._transcript_lock:
            if session_id in self._latest_transcript_for_gemini:
                del self._latest_transcript_for_gemini[session_id]
