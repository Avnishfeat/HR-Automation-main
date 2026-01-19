
import logging
from datetime import datetime
from typing import Optional, Dict
import threading
from app.core.ports.session_repository import SessionRepository

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
            # Note: Assuming synchronous call here, if db_handler is async we might need a wrapper or run_until_complete
            # BUT the original code was synchronous. The new SessionRepository is Protocol, implementation is MongoSessionRepository which IS async.
            # This method is called from background threads in the original code.
            # Since we are moving to async architecture, we should probably update this to be async or run sync.
            # However, looking at usage in `meet_interview_orchestrator.py` (which I haven't ported yet), it seems to be used in threads.
            # For now, I will keep the signature but inside I might need to handle async if I can.
            # Actually, `MongoSessionRepository` methods are `async def`. calling them from sync function returns a coroutine.
            # To fix this properly, I should probably make `process_and_log_transcript` async, but `stt_service` calls it?
            # Let's check `stt_service.py` again. It calls it in `_process_with_v1` (sync) or `_process_with_v2` (sync run in thread).
            # So `process_and_log_transcript` MUST be capable of running async code from sync context if it uses async DB methods.
            
            # Since I can't easily change the caller right now without refactoring STT, I will usage a helper to run async.
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
                
            if loop.is_running():
                 # We are in a thread with a running loop? No, usually not.
                 # If this is called from `stt_service` thread, there is no running loop in that thread.
                 # But we might need to target the main loop.
                 future = asyncio.run_coroutine_threadsafe(
                    self.db.add_message_to_session(
                        session_id, "user", transcript, audio_path, 
                        start_time, end_time, 
                        is_follow_up=is_follow_up_response,
                        turn_count=turn_count
                    ), loop)
                 future.result()
            else:
                 # No running loop, just run it (e.g. CLI testing)
                 loop.run_until_complete(
                    self.db.add_message_to_session(
                        session_id, "user", transcript, audio_path, 
                        start_time, end_time, 
                        is_follow_up=is_follow_up_response,
                        turn_count=turn_count
                    )
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
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()

            # Async fetch
            if loop.is_running():
                 future = asyncio.run_coroutine_threadsafe(self.db.get_full_session(session_id), loop)
                 session_data = future.result()
            else:
                 session_data = loop.run_until_complete(self.db.get_full_session(session_id))

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
            if loop.is_running():
                 future = asyncio.run_coroutine_threadsafe(self.db.save_transcript_text(session_id, full_text), loop)
                 success = future.result()
            else:
                 success = loop.run_until_complete(self.db.save_transcript_text(session_id, full_text))

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
