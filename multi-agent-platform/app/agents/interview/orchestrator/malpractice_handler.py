# app/orchestrator/malpractice_handler.py
"""
Handles malpractice detection and response during interviews.
Extracted from meet_interview_orchestrator.py for better separation of concerns.
"""
import logging
import threading
import time
import asyncio
from datetime import datetime, timezone, UTC
from typing import TYPE_CHECKING

from app.agents.interview.config.constants import SessionStatus

if TYPE_CHECKING:
    from .types import InterviewSession

logger = logging.getLogger(__name__)


class MalpracticeHandler:
    """Handles malpractice violations during interviews."""
    
    def __init__(self, session_mgr, interview_svc, audio_handler):
        self.session_mgr = session_mgr
        self.interview_svc = interview_svc
        self.audio_handler = audio_handler
        self._processing_by_session: dict[str, threading.Event] = {}
        self._processing_lock = threading.Lock()

    def _processing_event(self, session_id: str) -> threading.Event:
        with self._processing_lock:
            return self._processing_by_session.setdefault(session_id, threading.Event())

    def is_processing(self, session_id: str) -> bool:
        return self._processing_event(session_id).is_set()
    
    def handle_violation(self, session: "InterviewSession", count: int, violation_type: str, names: list):
        """Main handler for malpractice violations."""
        if violation_type == "candidate_disconnected":
            logger.warning("Handling candidate disconnection")
        else:
            logger.critical(f"Handling Malpractice: {violation_type}")
        
        processing = self._processing_event(session.session_id)
        if processing.is_set():
            return
        processing.set()
        
        # Dispatch to async handler to avoid blocking or 'coroutine never awaited' errors
        try:
            asyncio.get_running_loop().create_task(
                self._async_handle_violation(session, count, violation_type, names)
            )
        except RuntimeError:
            # Fallback if no running loop (shouldn't happen in our FastAPI app)
            logger.error("No running event loop found for malpractice handler.")
            processing.clear()
            
    async def _async_handle_violation(self, session: "InterviewSession", count: int, violation_type: str, names: list):
        try:
            session.stop_event.set()
            session_data = self.session_mgr.get_session(session.session_id)
            if violation_type == "candidate_disconnected":
                if session_data is not None:
                    session_data["status"] = SessionStatus.ERROR_CANDIDATE_LEFT
                logger.info("Candidate disconnected; ending session %s without malpractice warning", session.session_id)
                return
            if session_data is not None:
                session_data["status"] = SessionStatus.ERROR_MULTIPLE_PARTICIPANTS
            
            # Log to memory/logger
            incident_data = {
                'malpractice_incident': {
                    'type': violation_type,
                    'participant_count': count,
                    'participant_names': names,
                    'detected_at': datetime.now(timezone.utc).isoformat(),
                    'session_id': session.session_id
                },
                'status': SessionStatus.ERROR_MULTIPLE_PARTICIPANTS
            }
            logger.warning(f"Malpractice detected for {session.session_id}: {incident_data}")

            # Generate specific warning
            warning_text, should_terminate = self._get_warning_for_type(violation_type)
            
            await self._play_warning(session, warning_text)

            if should_terminate:
                await asyncio.sleep(2.0)
                await session.meet.leave_meeting()
            
        except Exception as e:
            logger.error(f"Error handling malpractice: {e}")
        finally:
            self._processing_event(session.session_id).clear()
    
    def _get_warning_for_type(self, violation_type: str) -> tuple:
        """Returns (warning_text, should_terminate) for violation type."""
        if violation_type == "companion_mode_detected":
            return (
                "I see you have joined using Companion Mode. "
                "While this feature is supported, for the purpose of this secure interview, "
                "we require a single active device. Please disconnect your companion device.",
                True
            )
        elif violation_type == "multiple_devices_same_account":
            return (
                "I have detected that you are logged in from multiple devices. "
                "This is not permitted. The interview will be terminated.",
                True
            )
        else:
            return (
                "I have detected an unauthorized person in the meeting. "
                "The session will now be terminated.",
                True
            )
    
    async def _play_warning(self, session: "InterviewSession", message: str):
        """Play audio warning and send chat message."""
        try:
            await session.meet.enable_microphone()
            await asyncio.sleep(1.0)
            
            cache_key = "warning_malpractice_generic"
            if "multiple devices" in message:
                cache_key = "warning_multiple_devices"
            
            audio_path = self.interview_svc.get_static_audio_path(message, cache_key)
            
            if audio_path:
                force_evt = threading.Event()
                await asyncio.to_thread(self.audio_handler.play_wav_file, audio_path, session.meet, force_evt)
                
            await self._send_chat_message(session)
                    
        except Exception:
            pass
    
    async def _send_chat_message(self, session: "InterviewSession"):
        """Send termination chat message."""
        try:
            await session.meet.send_chat_message(
                "INTERVIEW TERMINATED\n\n"
                "Multiple participants detected in this session.\n"
                "This is a violation of interview integrity guidelines.\n\n"
                "Our recruiting team will contact you regarding this incident."
            )
        except Exception:
            pass
    
    def log_incident(self, session_id: str, participant_count: int):
        """Log malpractice incident."""
        try:
            incident_data = {
                'malpractice_incident': {
                    'type': 'malpractice_violation',
                    'reason': 'multiple_participants',
                    'participant_count': participant_count,
                    'detected_at': datetime.now(timezone.utc).isoformat(),
                    'session_id': session_id,
                    'action_taken': 'interview_terminated'
                },
                'status': SessionStatus.ERROR_MULTIPLE_PARTICIPANTS,
                'terminated_at': datetime.now(timezone.utc).isoformat()
            }
            logger.warning(f"Malpractice logged for {session_id}: {incident_data}")
        except Exception as e:
            logger.error(f"Logging failed: {e}", exc_info=True)
    
    def set_termination_reason(self, session_id: str, reason: str):
        """Set termination reason."""
        try:
            logger.info(f"Session {session_id} terminated. Reason: {reason}")
        except Exception:
            pass
