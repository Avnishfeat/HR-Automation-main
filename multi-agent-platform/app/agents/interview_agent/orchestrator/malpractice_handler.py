
# app/services/interview/orchestrator/malpractice_handler.py
"""
Handles malpractice detection and response during interviews.
Extracted from meet_interview_orchestrator.py for better separation of concerns.
"""
import logging
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

from app.agents.interview_agent.utils.constants import SessionStatus

if TYPE_CHECKING:
    from app.agents.interview_agent.orchestrator.types import InterviewSession

logger = logging.getLogger(__name__)


import asyncio

class MalpracticeHandler:
    """Handles malpractice violations during interviews."""
    
    def __init__(self, session_mgr, interview_svc, audio_handler):
        self.session_mgr = session_mgr
        self.interview_svc = interview_svc
        self.audio_handler = audio_handler
        self.processing = threading.Event()
        self.loop = None
    
    def handle_violation(self, session: "InterviewSession", count: int, violation_type: str, names: list):
        """Main handler for malpractice violations."""
        logger.critical(f"Handling Malpractice: {violation_type}")
        
        if self.processing.is_set():
            return
        self.processing.set()
        
        try:
            session.stop_event.set()
            
            # Log to database
            incident_data = {
                'malpractice_incident': {
                    'type': violation_type,
                    'participant_count': count,
                    'participant_names': names,
                    'detected_at': datetime.utcnow().isoformat(),
                    'session_id': session.session_id
                },
                'status': SessionStatus.ERROR_MULTIPLE_PARTICIPANTS
            }
            
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self.session_mgr.db.update_session(session.session_id, incident_data),
                    self.loop
                )
            
            # Generate specific warning
            warning_text, should_terminate = self._get_warning_for_type(violation_type)
            
            self._play_warning(session, warning_text)

            if should_terminate:
                time.sleep(2.0)
                session.meet.leave_meeting()
            
        except Exception as e:
            logger.error(f"Error handling malpractice: {e}")
        finally:
            self.processing.clear()
    
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
    
    def _play_warning(self, session: "InterviewSession", message: str):
        """Play audio warning and send chat message."""
        try:
            session.meet.enable_microphone()
            time.sleep(1.0)
            
            cache_key = "warning_malpractice_generic"
            if "multiple devices" in message:
                cache_key = "warning_multiple_devices"
            
            # We call sync method here. If get_static_audio_path is async now, this breaks!
            # MeetInterviewOrchestrator uses await self.interview_svc.get_static_audio_path
            # But here we are in sync method called from thread.
            # We need to use run_coroutine_threadsafe or use a sync version if possible.
            # Since get_static_audio_path is async now, we MUST use loop to get audio path.
            
            audio_path = None
            if self.loop and self.interview_svc:
                future = asyncio.run_coroutine_threadsafe(
                    self.interview_svc.get_static_audio_path(message, cache_key),
                    self.loop
                )
                try:
                    audio_path = future.result(timeout=5)
                except Exception as e:
                    logger.error(f"Failed to get audio path in malpractice: {e}")
            
            if audio_path:
                force_evt = threading.Event()
                self.audio_handler.play_wav_file(audio_path, session.meet, force_evt)
                
            self._send_chat_message(session)
                    
        except Exception as e:
            logger.error(f"Error playing malpractice warning: {e}")
    
    def _send_chat_message(self, session: "InterviewSession"):
        """Send termination chat message."""
        try:
            session.meet.send_chat_message(
                "INTERVIEW TERMINATED\n\n"
                "Multiple participants detected in this session.\n"
                "This is a violation of interview integrity guidelines.\n\n"
                "Our recruiting team will contact you regarding this incident."
            )
        except Exception:
            pass
    
    def log_incident(self, session_id: str, candidate_id: str, participant_count: int):
        # Unused legacy method
        pass
    
    async def set_termination_reason(self, session_id: str, reason: str):
        """Set termination status and reason in database."""
        try:
            update_data = {
                "status": "terminated", 
                "termination_reason": reason,
                "ended_at": datetime.utcnow().isoformat()
            }
            await self.session_mgr.db.update_session(session_id, update_data)
        except Exception as e:
            logger.error(f"Failed to update session status on termination: {e}")
