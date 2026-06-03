# app/services/transcript_manager.py
import logging
from datetime import datetime, timezone, UTC
from typing import Optional, Dict, List
import threading

logger = logging.getLogger(__name__)

class TranscriptManager:
    """
    Manages all transcript-related operations in-memory.
    """

    def __init__(self):
        self._latest_transcript_for_gemini: Dict[str, Optional[str]] = {}
        self._conversation_history: Dict[str, List[Dict]] = {}
        self._transcript_lock = threading.Lock()

    def initialize_transcript_state(self, session_id: str):
        with self._transcript_lock:
            self._latest_transcript_for_gemini[session_id] = "[Candidate introduction pending]"
            self._conversation_history[session_id] = []
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
        """Update with interim transcript (user still speaking)."""
        with self._transcript_lock:
            if interim_text and len(interim_text) > 5:  # Ignore very short fragments
                self._latest_transcript_for_gemini[session_id] = f"[Speaking...] {interim_text}"

    def log_assistant_message(self, session_id: str, text: str, turn_count: int):
        """Logs bot message to history."""
        with self._transcript_lock:
            if session_id not in self._conversation_history:
                self._conversation_history[session_id] = []
            self._conversation_history[session_id].append({
                "role": "assistant",
                "text": text,
                "turn": turn_count,
                "timestamp": datetime.now(timezone.utc)
            })

    def process_and_log_transcript(
        self,
        session_id: str,
        audio_path: str,
        transcript: str,
        turn_count: int,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        is_follow_up_response: bool = False
    ) -> None:
        try:
            logger.info(f"(BG Thread) Logging user transcript (Turn {turn_count}): {transcript}")

            # 1. Log to memory history
            with self._transcript_lock:
                if session_id not in self._conversation_history:
                    self._conversation_history[session_id] = []
                self._conversation_history[session_id].append({
                    "role": "user",
                    "text": transcript,
                    "audio_path": audio_path,
                    "start_time": start_time,
                    "end_time": end_time,
                    "is_follow_up": is_follow_up_response,
                    "turn": turn_count,
                    "timestamp": datetime.now(timezone.utc)
                })

            # 2. Update In-Memory State for next question generation
            with self._transcript_lock:
                if transcript and not transcript.startswith("[Error") and transcript != "[Unintelligible]" and transcript.strip() != "[No response]":
                    self._latest_transcript_for_gemini[session_id] = transcript
                    logger.info(f"(BG Thread) Updated in-memory transcript for {session_id}")

        except Exception as e:
            logger.error(f"(BG Thread) Error in process_and_log_transcript: {e}", exc_info=True)

    def save_final_transcript(self, session_id: str) -> str:
        """
        Generates and saves the final formatted transcript string to disk.
        """
        try:
            with self._transcript_lock:
                history = self._conversation_history.get(session_id, [])

            if not history:
                logger.warning(f"TranscriptManager: No history found for {session_id}")
                return "No transcript generated."

            # Build the readable string
            lines = []
            lines.append(f"--- Interview Transcript ---")
            lines.append(f"Session ID: {session_id}")
            lines.append(f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            lines.append("--------------------------------\n")

            # Append Conversation
            for msg in history:
                role = msg.get("role", "unknown").capitalize()
                text = msg.get("text", "")
                turn = msg.get("turn", "?")
                ts = msg.get("timestamp")
                ts_str = ts.strftime('%H:%M:%S UTC') if ts else "N/A"

                lines.append(f"[{ts_str}] (Turn {turn}) {role}:\n{text}\n")

            full_text = "\n".join(lines)

            # Save to disk
            from pathlib import Path
            output_dir = Path("data") / session_id
            output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_dir / "transcript.txt", "w", encoding="utf-8") as f:
                f.write(full_text)

            logger.info(f"Final transcript saved to disk for {session_id}")
            return full_text

        except Exception as e:
            logger.error(f"TranscriptManager: Generation failed: {e}", exc_info=True)
            return f"Error generating transcript: {str(e)}"

    def get_history(self, session_id: str) -> List[Dict]:
        """Alias for get_conversation_history."""
        return self.get_conversation_history(session_id)

    def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Returns the raw conversation history for analysis."""
        with self._transcript_lock:
            return self._conversation_history.get(session_id, [])

    def clear_session_state(self, session_id: str):
        with self._transcript_lock:
            if session_id in self._latest_transcript_for_gemini:
                del self._latest_transcript_for_gemini[session_id]
            if session_id in self._conversation_history:
                del self._conversation_history[session_id]
