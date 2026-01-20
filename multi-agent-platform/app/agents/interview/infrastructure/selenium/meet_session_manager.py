# app/infrastructure/selenium/meet_session_manager.py
import logging
import time
import threading
import random
import string
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any
from PIL import Image
import urllib3

from app.agents.interview.services.analysis.video_integrity import VideoIntegrityAnalyzer
from .meet_controller import MeetController
from app.agents.interview.core.ports.session_repository import SessionRepository
from app.agents.interview.config.constants import (
    LoggingConfig,
    VideoConfig, 
    ParticipantThresholds, 
    InterviewTiming, 
    BrowserConfig,
    StoragePaths
)

logger = logging.getLogger(__name__)

class MeetSessionManager:
    CHROME_PROFILE_PATH = Path(StoragePaths.CHROME_PROFILE_ROOT).resolve()

    def __init__(self, db_handler: SessionRepository):
        self.db = db_handler
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        logger.info(" Session manager initialized (using persistent Chrome profiles)")

        # --- SNAPSHOT CONFIGURATION ---
        self.MAX_SNAPSHOTS = 9999  # Effectively unlimited - take snapshots for entire interview
        self.SNAPSHOT_INTERVAL = 4.0  # 4 seconds between snapshots

    def create_interview_session(
        self, 
        candidate_id: str, 
        session_id: str, 
        job_position: str = "Software Engineer", 
        meet_link: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates a session record in memory and optionally generates a Meet link."""
        meet_link = meet_link or self._generate_meet_link()
        
        if self.db.get_session(session_id):
            logger.info(f"Using existing session in DB: {session_id}")
        else:
            logger.warning(f"Session {session_id} not found in DB yet (will be created on join)")
            
        if meet_link:
            logger.info(f"Using Meet link: {meet_link}")
            
        return {
            "session_id": session_id,
            "candidate_id": candidate_id,
            "job_position": job_position,
            "meet_link": meet_link,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }

    def _generate_meet_link(self) -> str:
        part1 = ''.join(random.choices(string.ascii_lowercase, k=3))
        part2 = ''.join(random.choices(string.ascii_lowercase, k=4))
        part3 = ''.join(random.choices(string.ascii_lowercase, k=3))
        return f"https://meet.google.com/{part1}-{part2}-{part3}"

    def start_bot_session(
        self, 
        session_id: str, 
        meet_link: str, 
        candidate_id: str, 
        audio_device: Optional[int] = None, 
        enable_video: bool = True, 
        headless: bool = True, 
        video_capture_method: str = "javascript"
    ) -> bool:
        """Initializes the browser controller and joins the meeting."""
        try:
            logger.info(f"Starting bot session: {session_id} | Headless: {headless}")
            logger.info(f"Video: {'Enabled' if enable_video else 'Disabled'} | Method: {video_capture_method}")

            controller = MeetController(
                headless=headless,
                audio_device_index=audio_device,
                user_data_dir=str(self.CHROME_PROFILE_PATH),
                use_vb_audio=True
            )

            if not controller.setup_driver():
                logger.error(f"Failed to setup driver for session {session_id}")
                return False

            # --- CRITICAL PATCH: Increase Connection Pool Size ---
            try:
                if hasattr(controller, 'driver') and controller.driver:
                    remote_conn = controller.driver.command_executor
                    # Force pool size to 20 to handle concurrent threads (Monitor, Capture, Audio)
                    remote_conn._conn = urllib3.PoolManager(num_pools=1, maxsize=20)
                    logger.info(f"Session {session_id}: WebDriver Connection Pool patched (maxsize=20)")
            except Exception as e:
                logger.warning(f"Could not patch WebDriver pool: {e}")
            # -----------------------------------------------------

            bot_name = "AI Interviewer Bot"
            if not controller.join_meeting(meet_link, bot_name):
                logger.error(f"Failed to join meeting {session_id}")
                controller.cleanup()
                return False

            logger.info(f"Bot joined meeting: {session_id}")

            snapshot_dir = Path(StoragePaths.DATA_ROOT) / candidate_id / session_id / StoragePaths.SNAPSHOTS_DIR
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            # Store Session Data using RLock for thread safety
            # RLock allows the same thread (e.g. Capture) to re-acquire if needed
            session_lock = threading.RLock()

            self.active_sessions[session_id] = {
                'controller': controller,
                'meet_link': meet_link,
                'candidate_id': candidate_id,
                'status': 'active',
                'video_enabled': enable_video,
                'video_capture_method': video_capture_method,
                'snapshot_dir': snapshot_dir,
                'snapshot_count': 0,
                'snapshot_thread': None,
                'stop_capture': threading.Event(),
                'stop_interview': threading.Event(),
                'lock': session_lock, 
                'malpractice_flags': set(),
                'background_person_detections': 0,
                'last_background_warning_time': 0,
                'reconnection_count': 0,  # Track candidate disconnects/reconnects
                'capture_stats': {
                    'total_attempts': 0,
                    'successful_captures': 0,
                    'failed_captures': 0,
                    'js_captures': 0,
                    'screenshot_captures': 0
                }
            }
            
            logger.info(f"Waiting {InterviewTiming.MEET_UI_SETTLE_DELAY_SEC}s for Meet UI to settle...")
            time.sleep(InterviewTiming.MEET_UI_SETTLE_DELAY_SEC)

            try:
                self.send_meeting_guidelines(session_id)
            except Exception as e:
                logger.warning(f"Could not send guidelines: {e}")
            
            # NOTE: Video capture is NOT started here - it's started in background.py 
            # AFTER wait_for_candidate() to avoid false anomaly detection before interview

            return True

        except Exception as e:
            logger.error(f"Error starting bot session: {e}", exc_info=True)
            return False

    def _start_candidate_video_capture(self, session_id: str):
        session = self.active_sessions.get(session_id)
        if not session: return

        stop_event = session.get('stop_capture')
        if not stop_event: stop_event = session.get('stop_interview')

        controller = session.get('controller')
        session_lock = session.get('lock')
        
        if not stop_event or not controller or not session_lock:
            logger.error(f"Cannot start video capture for {session_id}: Components missing")
            return

        integrity_analyzer = VideoIntegrityAnalyzer()

        def capture_loop():
            logger.info(f"Video capture thread started for {session_id}")
            session_dir = Path(StoragePaths.CAPTURED_IMAGES_DIR) / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            while stop_event and not stop_event.is_set():
                try:
                    # No snapshot limit - capture for entire interview duration

                    image_bytes = None
                    capture_source = "none"

                    # 2. CAPTURE WITH LOCK
                    with session_lock:
                        try:
                            # Try JS first (Fast)
                            js_res = controller.capture_candidate_video_js()
                            if js_res:
                                image_bytes = js_res[0]
                                capture_source = "js_video"
                            else:
                                # Fallback to screenshot
                                image_bytes = controller.capture_candidate_video_screenshot()
                                capture_source = "screenshot"
                        except Exception as e:
                            logger.warning(f"Capture error: {e}")

                    if image_bytes:
                        # 3. INTEGRITY CHECK (Global & Local Motion)
                        integrity_status = integrity_analyzer.check_frame(image_bytes)
                        if integrity_status != "ok":
                            self._handle_video_integrity_failure(session_id, integrity_status)
                        
                        # 4. SAVE
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        filename = f"snap_{timestamp}_{capture_source}.jpg"
                        filepath = session_dir / filename
                        
                        with open(filepath, "wb") as f:
                            f.write(image_bytes)
                        
                        current_count = session.get('snapshot_count', 0)
                        session['snapshot_count'] = current_count + 1
                        logger.debug(f"Saved snapshot {filename} ({integrity_status})")
                    else:
                        logger.warning(f"Failed to capture frame for {session_id}")

                except Exception as e:
                    logger.error(f"Error in video capture loop: {e}")
                
                # 5. FIXED INTERVAL Wait (4.0s)
                if stop_event.wait(timeout=self.SNAPSHOT_INTERVAL):
                    break

            logger.info(f"Video capture thread stopped for {session_id}")

        thread = threading.Thread(target=capture_loop, daemon=True, name=f"VidCap-{session_id}")
        session['snapshot_thread'] = thread
        thread.start()

    def capture_snapshot_now(self, session_id: str) -> Optional[bytes]:
        session = self.active_sessions.get(session_id)
        if not session: return None
        
        controller = session.get('controller')
        lock = session.get('lock')

        if not controller or not lock: return None
        
        try:
            with lock:
                result = controller.capture_candidate_video_js()
                if result: return result[0]
                return controller.capture_candidate_video_screenshot()
        except Exception as e:
            logger.error(f"Immediate capture failed for {session_id}: {e}")
            return None

    def _handle_video_integrity_failure(self, session_id: str, status: str):
        session = self.active_sessions.get(session_id)
        if not session: return

        if 'malpractice_flags' not in session:
            session['malpractice_flags'] = set()
        
        if isinstance(session['malpractice_flags'], list):
            session['malpractice_flags'] = set(session['malpractice_flags'])

        # Handle multiple faces detection (background person)
        if status == "multiple_faces":
            session['background_person_detections'] = session.get('background_person_detections', 0) + 1
            self._send_background_person_warning(session_id, session)
            return

        flag_code = f"fake_camera_{status}"
        
        if flag_code not in session['malpractice_flags']:
            logger.warning(f"🚨 VIDEO ANOMALY DETECTED in {session_id}: {status.upper()}")
            session['malpractice_flags'].add(flag_code)

    def _send_background_person_warning(self, session_id: str, session: dict):
        """Send chat warning for background person detection (throttled to once per 60s)."""
        current_time = time.time()
        last_warning = session.get('last_background_warning_time', 0)
        
        # Throttle warnings to once per 60 seconds
        if current_time - last_warning < 60:
            return
        
        session['last_background_warning_time'] = current_time
        
        controller = session.get('controller')
        lock = session.get('lock')
        
        if not controller or not lock:
            return
        
        # Send warning in background thread to avoid blocking video capture
        def send_warning():
            warning_message = (
                "SYSTEM NOTICE: Additional person detected in frame.\n\n"
                "Please ensure you are alone in a private space during the interview.\n"
                "This has been logged for review."
            )
            try:
                with lock:
                    controller.send_chat_message(warning_message)
                logger.warning(f"Background person warning sent for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to send background person warning: {e}")
        
        threading.Thread(target=send_warning, daemon=True, name=f"BgWarn-{session_id}").start()

    def get_background_person_count(self, session_id: str) -> int:
        """Get the count of background person detections for a session."""
        session = self.active_sessions.get(session_id)
        if session:
            return session.get('background_person_detections', 0)
        return 0

    def get_reconnection_count(self, session_id: str) -> int:
        """Get the count of candidate reconnections for a session."""
        session = self.active_sessions.get(session_id)
        if session:
            return session.get('reconnection_count', 0)
        return 0
    
    def increment_reconnection_count(self, session_id: str) -> int:
        """Increment and return the reconnection count when candidate rejoins."""
        session = self.active_sessions.get(session_id)
        if session:
            session['reconnection_count'] = session.get('reconnection_count', 0) + 1
            logger.warning(f"Candidate reconnected (count: {session['reconnection_count']}) for session {session_id}")
            return session['reconnection_count']
        return 0

    def get_snapshot_count(self, session_id: str) -> int:
        session = self.active_sessions.get(session_id)
        if session:
            return session.get('snapshot_count', 0)
        
        try:
            session_data = self.db.get_session(session_id)
            if session_data:
                candidate_id = session_data.get('candidate_id')
                if candidate_id:
                    snapshot_dir = Path(StoragePaths.DATA_ROOT) / candidate_id / session_id / StoragePaths.SNAPSHOTS_DIR
                    if snapshot_dir.exists():
                        return len(list(snapshot_dir.glob("*.jpg")))
        except Exception as e:
            logger.error(f"Error counting disk snapshots: {e}")
        return 0

    def get_capture_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.active_sessions.get(session_id)
        if session:
            stats = session.get('capture_stats', {})
            total = stats.get('total_attempts', 0)
            success = stats.get('successful_captures', 0)
            rate = f"{success}/{total}" if total > 0 else "N/A"
            
            return {
                'snapshot_count': session.get('snapshot_count', 0),
                'total_attempts': total,
                'successful_captures': success,
                'failed_captures': stats.get('failed_captures', 0),
                'js_captures': stats.get('js_captures', 0),
                'screenshot_captures': stats.get('screenshot_captures', 0),
                'success_rate': rate
            }
        return None
    
    def send_meeting_guidelines(self, session_id: str) -> bool:
        session = self.active_sessions.get(session_id)
        if not session: return False
        
        controller = session.get('controller')
        lock = session.get('lock')

        if not controller or not lock:
            logger.error(f"Session/Controller/Lock missing for {session_id}")
            return False
        
        guidelines = (
            "Interview Guidelines:\n"
            "1. Camera: Please keep your camera ON throughout the interview\n"
            "2. Microphone: Enable your mic when speaking\n"
            "3. Environment: Ensure you're in a quiet space\n"
            "4. Questions: If you need a question repeated, just ask\n"
            "5. Duration: This interview will last approximately 10 minutes\n\n"
            "Good luck!"
        )
        
        logger.info(f"Sending guidelines to chat for session {session_id}")
        
        success = False
        try:
            with lock:
                success = controller.send_chat_message(guidelines)
        except Exception as e:
            logger.error(f"Failed to send guidelines due to error: {e}")
            return False
        
        if success:
            logger.info("Guidelines sent successfully")
        else:
            logger.warning("Failed to send guidelines")
        
        return success

    def wait_for_candidate(
        self, 
        session_id: str, 
        timeout: int = InterviewTiming.CANDIDATE_JOIN_TIMEOUT_SEC
    ) -> bool:
        session = self.active_sessions.get(session_id)
        if not session: return False
        
        controller = session.get('controller')
        lock = session.get('lock')

        if not controller or not lock:
            logger.error(f"Session/Ctrl/Lock missing wait {session_id}")
            return False
        
        start_time = time.time()
        logger.info(f"Waiting for candidate (Timeout: {timeout}s)...")
        
        consecutive_joins = 0
        required_stable_checks = VideoConfig.REQUIRED_STABLE_CHECKS
        check_interval = VideoConfig.STABILITY_CHECK_INTERVAL_SEC
        last_checked_count = 1 

        while time.time() - start_time < timeout:
            stop_event = session.get('stop_interview')
            if stop_event and stop_event.is_set():
                return False

            try:
                # Protect the check with lock
                with lock:
                    participant_count = controller.get_participant_count() 
                
                logger.debug(f"Participant count check: {participant_count}")
                last_checked_count = participant_count 

                if participant_count == ParticipantThresholds.MIN_VALID_COUNT:
                    consecutive_joins += 1
                    logger.info(f"Potential stable join (Count={participant_count}). Stable checks: {consecutive_joins}/{required_stable_checks}")
                    
                    if consecutive_joins >= required_stable_checks:
                        logger.info(f"Candidate joined stably! Total participants: {participant_count}")
                        session['status'] = 'candidate_joined'
                        session['candidate_joined_at'] = datetime.utcnow().isoformat()
                        return True 

                elif participant_count > ParticipantThresholds.MAX_VALID_COUNT:
                     logger.error(f"Too many participants ({participant_count}) detected. Aborting.")
                     session['status'] = 'aborted_multiple_participants'
                     return False 
                else: 
                    if consecutive_joins > 0:
                        logger.info("Count dropped below expected. Resetting stable checks.")
                    consecutive_joins = 0

                if stop_event and stop_event.wait(check_interval):
                    return False

            except Exception as e:
                logger.error(f"Error checking participants: {e}", exc_info=True)
                consecutive_joins = 0
                if stop_event and stop_event.wait(check_interval):
                    return False

        if last_checked_count > ParticipantThresholds.MAX_VALID_COUNT:
             session['status'] = 'aborted_multiple_participants_timeout'
        else:
            logger.warning(f" Timeout waiting for candidate {session_id} (Final count: {last_checked_count})")
            
        return False

    def end_session(self, session_id: str):
        session = self.active_sessions.pop(session_id, None)
        if not session:
            return

        try:
            logger.info(f"Ending session: {session_id}")
            
            if session.get('stop_interview') and not session['stop_interview'].is_set():
                session['stop_interview'].set()

            if session.get('video_enabled'):
                if session.get('stop_capture') and not session['stop_capture'].is_set():
                    session['stop_capture'].set()
                    
                capture_thread = session.get('snapshot_thread')
                if capture_thread and capture_thread.is_alive():
                    capture_thread.join(timeout=5)

            controller = session.get('controller')
            lock = session.get('lock')

            if controller:
                try:
                    if lock:
                        with lock:
                            controller.leave_meeting()
                            controller.cleanup()
                    else:
                        controller.leave_meeting()
                        controller.cleanup()
                except Exception as e:
                    logger.error(f"Error during controller cleanup: {e}")

            logger.info(f"Session {session_id} ended. Final Snaps: {session.get('snapshot_count', 0)}")

        except Exception as e:
            logger.error(f"Error ending session {session_id}: {e}", exc_info=True)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.active_sessions.get(session_id)

    def get_all_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        active_sessions_copy = dict(self.active_sessions)
        summary = {}
        for sid, session in active_sessions_copy.items():
             stats = session.get('capture_stats', {})
             summary[sid] = {
                'status': session.get('status', '?'),
                'candidate_id': session.get('candidate_id'),
                'meet_link': session.get('meet_link'),
                'snaps': session.get('snapshot_count', 0)
             }
        return summary