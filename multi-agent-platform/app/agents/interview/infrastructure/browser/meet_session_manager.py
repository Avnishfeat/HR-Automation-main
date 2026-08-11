# app/infrastructure/browser/meet_session_manager.py
import logging
import asyncio
from datetime import datetime, timezone, UTC
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
        self.start_failures: Dict[str, str] = {}
        self.SNAPSHOT_INTERVAL = 4.0

    async def start_bot_session(self, session_id, meet_link, audio_device=None, enable_video=True, headless=True, video_capture_method="javascript") -> bool:
        try:
            if self.active_sessions:
                self.start_failures[session_id] = SessionStatus.ERROR_CAPACITY_REACHED
                logger.error("Cannot start %s: another interview is already active", session_id)
                return False

            controller = MeetController(headless=headless, audio_device_index=audio_device, user_data_dir=str(self.CHROME_PROFILE_PATH), use_vb_audio=True)
            if not await controller.setup_driver():
                self.start_failures[session_id] = SessionStatus.ERROR_JOIN_FAILED
                return False
            if not await controller.join_meeting(meet_link, "AI Interviewer Bot"):
                await controller.cleanup()
                self.start_failures[session_id] = SessionStatus.ERROR_JOIN_FAILED
                return False

            self.active_sessions[session_id] = {
                'controller': controller, 'meet_link': meet_link, 'status': SessionStatus.ACTIVE_INTERVIEWING,
                'video_enabled': enable_video, 'video_capture_method': video_capture_method,
                'snapshot_count': 0, 'snapshot_task': None,
                'stop_capture': asyncio.Event(), 'stop_interview': asyncio.Event(),
                'lock': asyncio.Lock(), 'malpractice_flags': set(), 'background_person_detections': 0,
                'last_background_warning_time': 0, 'reconnection_count': 0
            }
            await asyncio.sleep(InterviewTiming.MEET_UI_SETTLE_DELAY_SEC)
            return True
        except Exception as e:
            logger.error(f"Error starting bot session {session_id}: {e}", exc_info=True)
            self.start_failures[session_id] = SessionStatus.ERROR_JOIN_FAILED
            return False

    def _start_candidate_video_capture(self, session_id: str):
        session = self.active_sessions.get(session_id)
        if not session: return
        stop_event = session.get('stop_capture')
        stop_interview_event = session.get('stop_interview')
        controller = session.get('controller')
        lock = session.get('lock')
        
        if not stop_event or not controller or not lock:
            logger.error(f"Cannot start video capture for {session_id}: missing runtime state")
            return

        integrity_analyzer = VideoIntegrityAnalyzer()
        snapshot_dir = Path(StoragePaths.DATA_ROOT) / session_id / StoragePaths.CAPTURED_IMAGES_DIR
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        async def capture_loop():
            logger.info(f"Video capture task started for {session_id}")
            while not stop_event.is_set() and not stop_interview_event.is_set():
                try:
                    img_bytes = None
                    async with lock:
                        res = await controller.capture_candidate_video_js()
                        if res: img_bytes = res[0]
                        else: img_bytes = await controller.capture_candidate_video_screenshot()

                    if img_bytes:
                        status = integrity_analyzer.check_frame(img_bytes)
                        if status != "ok": self._handle_video_integrity_failure(session_id, status)

                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        path = snapshot_dir / f"snap_{timestamp}.jpg"
                        with open(path, "wb") as f: f.write(img_bytes)
                        session['snapshot_count'] += 1
                except Exception as e:
                    logger.warning(f"Video capture failed for {session_id}: {e}")
                
                # Wait for SNAPSHOT_INTERVAL or stop_event
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.SNAPSHOT_INTERVAL)
                    break # if stop_event is set, it won't timeout, so we break
                except asyncio.TimeoutError:
                    pass # timeout reached, continue loop
                    
            logger.info(f"Video capture task stopped for {session_id}")

        task = asyncio.create_task(capture_loop(), name=f"VidCap-{session_id[:8]}")
        session['snapshot_task'] = task

    async def capture_snapshot_now(self, session_id: str) -> Optional[bytes]:
        session = self.active_sessions.get(session_id)
        if not session:
            return None

        controller = session.get('controller')
        lock = session.get('lock')
        if not controller or not lock:
            return None

        try:
            async with lock:
                result = await controller.capture_candidate_video_js()
                if result:
                    return result[0]
                return await controller.capture_candidate_video_screenshot()
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

    async def wait_for_candidate(self, session_id, timeout=InterviewTiming.CANDIDATE_JOIN_TIMEOUT_SEC):
        session = self.active_sessions.get(session_id)
        if not session: return False
        import time
        ctrl = session['controller']; lock = session['lock']
        start = time.time()
        consecutive_joins = 0

        logger.info(f"Session {session_id}: Waiting for candidate to join (Timeout: {timeout}s)...")
        last_log_time = start

        while time.time() - start < timeout:
            if session['stop_interview'].is_set(): return False

            # Log periodic wait status every 30 seconds
            current_time = time.time()
            if current_time - last_log_time >= 30:
                elapsed = int(current_time - start)
                logger.info(f"Session {session_id}: Still waiting for candidate... ({elapsed}s elapsed)")
                last_log_time = current_time

            try:
                async with lock: count = await ctrl.get_participant_count()
                if count >= ParticipantThresholds.MIN_VALID_COUNT:
                    consecutive_joins += 1
                    if consecutive_joins >= VideoConfig.REQUIRED_STABLE_CHECKS:
                        logger.info(f"Session {session_id}: Candidate joined successfully!")
                        session['status'] = SessionStatus.CANDIDATE_JOINED
                        session['candidate_joined_at'] = datetime.now(timezone.utc).isoformat()
                        return True
                else:
                    consecutive_joins = 0
            except Exception as e:
                logger.warning(f"Participant count check failed for {session_id}: {e}")
                consecutive_joins = 0
                
                # If browser or page is closed, abort immediately to avoid spamming errors
                if not ctrl.page or ctrl.page.is_closed() or not ctrl.browser:
                    logger.error(f"Session {session_id}: Browser/Page closed unexpectedly during wait_for_candidate.")
                    return False

            try:
                await asyncio.wait_for(session['stop_interview'].wait(), timeout=VideoConfig.STABILITY_CHECK_INTERVAL_SEC)
                return False # Stop event set
            except asyncio.TimeoutError:
                pass # Timeout reached, continue

        logger.warning(f"Session {session_id}: Candidate join timeout reached ({timeout}s).")
        return False
    async def end_session(self, session_id: str):
        session = self.active_sessions.pop(session_id, None)
        if not session: return
        session['stop_interview'].set()
        session['stop_capture'].set()
        capture_task = session.get('snapshot_task')
        if capture_task and not capture_task.done():
            # Wait for task to finish gracefully
            try:
                await asyncio.wait_for(capture_task, timeout=5.0)
            except asyncio.TimeoutError:
                capture_task.cancel()
                try:
                    await capture_task
                except asyncio.CancelledError:
                    pass
        try:
            async with session['lock']:
                await session['controller'].leave_meeting()
                await session['controller'].cleanup()
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
    def get_start_failure(self, session_id: str): return self.start_failures.pop(session_id, None)
    def get_all_active_sessions(self): return dict(self.active_sessions)
    def can_accept_session(self): return not self.active_sessions

    async def shutdown_all_sessions(self):
        """Close every active browser context during process shutdown."""
        for session_id in list(self.active_sessions):
            await self.end_session(session_id)
