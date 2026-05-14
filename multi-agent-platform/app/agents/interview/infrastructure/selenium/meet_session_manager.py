# app/infrastructure/selenium/meet_session_manager.py
import logging
import time
import threading
import urllib3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

from app.agents.interview.services.analysis.video_integrity import VideoIntegrityAnalyzer
from .meet_controller import MeetController
from app.agents.interview.config.constants import (
    VideoConfig,
    InterviewTiming,
    StoragePaths,
    SessionStatus,
    ParticipantThresholds,
)

logger = logging.getLogger(__name__)

class MeetSessionManager:
    CHROME_PROFILE_PATH = Path(StoragePaths.CHROME_PROFILE_ROOT).resolve()

    def __init__(self):
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.SNAPSHOT_INTERVAL = 4.0

    def start_bot_session(self, session_id, meet_link, audio_device=None, enable_video=True, headless=True, video_capture_method="javascript") -> bool:
        try:
            controller = MeetController(headless=headless, audio_device_index=audio_device, user_data_dir=str(self.CHROME_PROFILE_PATH), use_vb_audio=True)
            if not controller.setup_driver(): return False
            self._patch_webdriver_connection_pool(controller, session_id)
            if not controller.join_meeting(meet_link, "AI Interviewer Bot"):
                controller.cleanup()
                return False

            self.active_sessions[session_id] = {
                'controller': controller, 'meet_link': meet_link, 'status': SessionStatus.ACTIVE_INTERVIEWING,
                'video_enabled': enable_video, 'video_capture_method': video_capture_method,
                'snapshot_count': 0, 'snapshot_thread': None,
                'stop_capture': threading.Event(), 'stop_interview': threading.Event(),
                'lock': threading.RLock(), 'malpractice_flags': set(), 'background_person_detections': 0,
                'last_background_warning_time': 0, 'reconnection_count': 0
            }
            time.sleep(InterviewTiming.MEET_UI_SETTLE_DELAY_SEC)
            return True
        except Exception as e:
            logger.error(f"Error starting bot session {session_id}: {e}", exc_info=True)
            return False

    def _patch_webdriver_connection_pool(self, controller: MeetController, session_id: str) -> None:
        """Increase Selenium's localhost HTTP pool for concurrent Meet operations."""
        try:
            driver = getattr(controller, "driver", None)
            if not driver:
                return

            executor = getattr(driver, "command_executor", None)
            if not executor:
                return

            if hasattr(executor, "_conn"):
                executor._conn = urllib3.PoolManager(num_pools=1, maxsize=20, block=False)
                logger.info(f"Session {session_id}: WebDriver connection pool patched (maxsize=20)")
        except Exception as e:
            logger.warning(f"Session {session_id}: Could not patch WebDriver pool: {e}")

    def _start_candidate_video_capture(self, session_id: str):
        session = self.active_sessions.get(session_id)
        if not session: return
        stop_event = session.get('stop_capture') or session.get('stop_interview')
        controller = session.get('controller'); lock = session.get('lock')
        if not stop_event or not controller or not lock:
            logger.error(f"Cannot start video capture for {session_id}: missing runtime state")
            return

        integrity_analyzer = VideoIntegrityAnalyzer()
        snapshot_dir = Path(StoragePaths.DATA_ROOT) / session_id / StoragePaths.CAPTURED_IMAGES_DIR
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        def capture_loop():
            logger.info(f"Video capture thread started for {session_id}")
            while not stop_event.is_set():
                try:
                    img_bytes = None
                    with lock:
                        res = controller.capture_candidate_video_js()
                        if res: img_bytes = res[0]
                        else: img_bytes = controller.capture_candidate_video_screenshot()

                    if img_bytes:
                        status = integrity_analyzer.check_frame(img_bytes)
                        if status != "ok": self._handle_video_integrity_failure(session_id, status)

                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        path = snapshot_dir / f"snap_{timestamp}.jpg"
                        with open(path, "wb") as f: f.write(img_bytes)
                        session['snapshot_count'] += 1
                except Exception as e:
                    logger.warning(f"Video capture failed for {session_id}: {e}")
                if stop_event.wait(timeout=self.SNAPSHOT_INTERVAL): break
            logger.info(f"Video capture thread stopped for {session_id}")

        thread = threading.Thread(target=capture_loop, daemon=True, name=f"VidCap-{session_id[:8]}")
        session['snapshot_thread'] = thread
        thread.start()

    def capture_snapshot_now(self, session_id: str) -> Optional[bytes]:
        session = self.active_sessions.get(session_id)
        if not session:
            return None

        controller = session.get('controller')
        lock = session.get('lock')
        if not controller or not lock:
            return None

        try:
            with lock:
                result = controller.capture_candidate_video_js()
                if result:
                    return result[0]
                return controller.capture_candidate_video_screenshot()
        except Exception as e:
            logger.error(f"Immediate capture failed for {session_id}: {e}")
            return None

    def _handle_video_integrity_failure(self, session_id, status):
        session = self.active_sessions.get(session_id)
        if not session: return
        if status == "multiple_faces":
            session['background_person_detections'] += 1
            # Throttled chat warning could go here
            return
        session['malpractice_flags'].add(f"fake_camera_{status}")

    def get_snapshot_count(self, session_id):
        session = self.active_sessions.get(session_id)
        if session:
            return session.get('snapshot_count', 0)
        snapshot_dir = Path(StoragePaths.DATA_ROOT) / session_id / StoragePaths.CAPTURED_IMAGES_DIR
        return len(list(snapshot_dir.glob("*.jpg"))) if snapshot_dir.exists() else 0

    def get_background_person_count(self, session_id):
        return self.active_sessions.get(session_id, {}).get('background_person_detections', 0)

    def get_reconnection_count(self, session_id):
        return self.active_sessions.get(session_id, {}).get('reconnection_count', 0)

    def increment_reconnection_count(self, session_id):
        session = self.active_sessions.get(session_id)
        if session:
            session['reconnection_count'] += 1
            return session['reconnection_count']
        return 0

    def wait_for_candidate(self, session_id, timeout=InterviewTiming.CANDIDATE_JOIN_TIMEOUT_SEC):
        session = self.active_sessions.get(session_id)
        if not session: return False
        ctrl = session['controller']; lock = session['lock']; start = time.time()
        consecutive_joins = 0
        while time.time() - start < timeout:
            if session['stop_interview'].is_set(): return False
            try:
                with lock: count = ctrl.get_participant_count()
                if count == ParticipantThresholds.MIN_VALID_COUNT:
                    consecutive_joins += 1
                    if consecutive_joins >= VideoConfig.REQUIRED_STABLE_CHECKS:
                        session['status'] = SessionStatus.CANDIDATE_JOINED
                        session['candidate_joined_at'] = datetime.utcnow().isoformat()
                        return True
                elif count > ParticipantThresholds.MAX_VALID_COUNT:
                    session['status'] = SessionStatus.ABORTED_MULTIPLE_PARTICIPANTS
                    return False
                else:
                    consecutive_joins = 0
            except Exception as e:
                logger.warning(f"Participant count check failed for {session_id}: {e}")
                consecutive_joins = 0
            if session['stop_interview'].wait(VideoConfig.STABILITY_CHECK_INTERVAL_SEC):
                return False
        return False

    def end_session(self, session_id: str):
        session = self.active_sessions.pop(session_id, None)
        if not session: return
        session['stop_interview'].set()
        session['stop_capture'].set()
        capture_thread = session.get('snapshot_thread')
        if capture_thread and capture_thread.is_alive():
            capture_thread.join(timeout=5)
        try:
            with session['lock']:
                session['controller'].leave_meeting()
                session['controller'].cleanup()
        except Exception as e:
            logger.warning(f"Error ending session {session_id}: {e}")

    def request_session_stop(self, session_id: str):
        session = self.active_sessions.get(session_id)
        if session:
            session['status'] = SessionStatus.STOP_REQUESTED
            session['stop_interview'].set()
            session['stop_capture'].set()
            return True
        return False

    def get_session(self, session_id): return self.active_sessions.get(session_id)
    def get_all_active_sessions(self): return dict(self.active_sessions)
    def can_accept_session(self): return len(self.active_sessions) < 5
