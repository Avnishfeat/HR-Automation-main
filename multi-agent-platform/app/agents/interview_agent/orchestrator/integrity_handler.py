
# app/services/interview/orchestrator/integrity_handler.py
"""
Handles video integrity checks during interviews.
Extracted from meet_interview_orchestrator.py for better separation of concerns.
"""
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.interview_agent.orchestrator.types import InterviewSession

logger = logging.getLogger(__name__)


class IntegrityHandler:
    """Handles video integrity checks and violations."""
    
    def __init__(self, session_mgr, interview_svc, audio_handler, video_analyzer):
        self.session_mgr = session_mgr
        self.interview_svc = interview_svc
        self.audio_handler = audio_handler
        self.video_analyzer = video_analyzer
    
    def check_video_integrity(self, session: "InterviewSession") -> bool:
        """
        Captures a frame and checks for integrity violations (Frozen, Loop, Motion).
        Returns True if a violation was handled, False otherwise.
        
        Warning behavior:
        - Audio warnings limited to MAX_AUDIO_WARNINGS (2) per session
        - After limit, violations are silently flagged for analysis
        - Requires sustained issues (10+ seconds) before first warning
        """
        try:
            image_data = session.meet.capture_candidate_video()
            if not image_data:
                return False
            
            image_bytes = image_data[0]  # (bytes, w, h)
            
            # Analyze frame
            status = self.video_analyzer.check_frame(image_bytes)
            
            if status == "ok":
                # Reset sustained violation timer when OK
                session_data = self.session_mgr.get_session(session.session_id)
                if session_data:
                    session_data['violation_start_time'] = None
                return False

            # Map status to violation type
            violation_type = self._get_violation_type(status)

            if violation_type:
                session_data = self.session_mgr.get_session(session.session_id)
                
                # Initialize tracking if needed
                if 'motion_warning_count' not in session_data:
                    session_data['motion_warning_count'] = 0
                if 'total_motion_violations' not in session_data:
                    session_data['total_motion_violations'] = 0
                if 'violation_start_time' not in session_data:
                    session_data['violation_start_time'] = None
                
                MAX_AUDIO_WARNINGS = 2
                SUSTAINED_DURATION = 10  # Seconds of sustained violation before warning
                
                # Track sustained violation duration
                current_time = time.time()
                if session_data['violation_start_time'] is None:
                    session_data['violation_start_time'] = current_time
                
                violation_duration = current_time - session_data['violation_start_time']
                
                # Always count violations for analysis
                session_data['total_motion_violations'] += 1
                
                # Only warn if sustained for SUSTAINED_DURATION seconds
                if violation_duration < SUSTAINED_DURATION:
                    return False  # Too brief, don't warn yet
                
                # Check if we've exceeded audio warning limit
                if session_data['motion_warning_count'] >= MAX_AUDIO_WARNINGS:
                    # Silent flag - just log, no audio warning
                    logger.info(f"Motion violation silently flagged (warning limit reached: {session_data['motion_warning_count']})")
                    return False
                
                # Throttle warnings (once every 60s)
                last_warning = session_data.get('last_integrity_warning_time', 0)
                
                if current_time - last_warning > 60:
                    self._handle_violation(session, violation_type)
                    session_data['last_integrity_warning_time'] = current_time
                    session_data['motion_warning_count'] += 1
                    session_data['violation_start_time'] = None  # Reset after warning
                    logger.info(f"Motion warning {session_data['motion_warning_count']}/{MAX_AUDIO_WARNINGS}")
                    return True

        except Exception as e:
            logger.error(f"Integrity check error: {e}")
        
        return False
    
    def _get_violation_type(self, status: str) -> str:
        """Maps status code to human-readable violation type."""
        mapping = {
            "frozen": "Frozen Video Feed",
            "looping": "Looping Video Feed",
            "camera_moving": "Excessive Camera Movement"
        }
        return mapping.get(status)
    
    def _handle_violation(self, session: "InterviewSession", violation_type: str):
        """Handle a video integrity violation."""
        logger.warning(f"INTEGRITY VIOLATION: {violation_type}")
        
        # Log to DB
        self.session_mgr.db.update_session(session.session_id, {
            "integrity_status": "warning",
            "last_integrity_issue": violation_type,
            "integrity_failure_time": datetime.now()
        })

        # Get warning message
        warning_text = self._get_warning_message(violation_type)

        # Play Warning
        session.meet.enable_microphone()
        audio_path = self.interview_svc.get_static_audio_path(
            warning_text, 
            f"warn_{violation_type.lower().replace(' ', '_')}"
        )
        self.audio_handler.play_wav_file(audio_path, session.meet, session.stop_event)
        
        # Send Chat
        try:
            session.meet.send_chat_message(f"SYSTEM WARNING: {violation_type} detected.")
        except Exception:
            pass
    
    def _get_warning_message(self, violation_type: str) -> str:
        """Get warning message for violation type."""
        if violation_type == "Excessive Camera Movement":
            return (
                "I detect that you are moving around the room. "
                "Please remain seated and keep your device stationary "
                "for the duration of the interview."
            )
        else:
            return (
                "I am detecting irregularities in your video feed. "
                "Please ensure your camera is live and functioning correctly."
            )
