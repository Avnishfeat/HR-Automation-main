# app/orchestrator/meet_interview_orchestrator.py
import logging
import threading
import time
import random
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

# Updated imports to point to new locations
from app.agents.interview.services.analysis.liveness_service import LivenessChallengeService
from app.agents.interview.infrastructure.selenium.meet_session_manager import MeetSessionManager
from app.agents.interview.services.interview_service import InterviewService
from app.agents.interview.services.audio.stt_service import STTService
from app.agents.interview.services.audio.audio_handler import AudioHandler
from app.agents.interview.services.participant_monitor import ParticipantMonitor
from app.agents.interview.services.analysis.video_integrity import VideoIntegrityAnalyzer
# New Orchestrator Components
from .types import (
    InterviewSession, InterviewPhase, ResponseData, InterviewState
)
from .state_manager import InterviewStateManager
from .response_handler import InterviewResponseHandler
from .malpractice_handler import MalpracticeHandler
from .integrity_handler import IntegrityHandler

# Config
from app.agents.interview.config.constants import (
    ErrorMessages, InterviewTiming, SessionStatus, TerminationReason, 
    StaticMessages, ParticipantThresholds
)
from app.agents.interview.utils.audio_file_utils import get_user_audio_path_for_stt

logger = logging.getLogger(__name__)

# --- NEW: Thread-Safe Proxy ---
class ThreadSafeControllerProxy:
    """
    Wraps the MeetController to ensure all method calls are protected by the session lock.
    This prevents the ParticipantMonitor (thread) and VideoCapture (thread) from 
    crashing the Selenium connection pool.
    """
    def __init__(self, controller, lock):
        self._controller = controller
        self._lock = lock

    def __getattr__(self, name):
        # Get the actual attribute from the controller
        attr = getattr(self._controller, name)
        
        # If it's a method, wrap it in the lock
        if callable(attr):
            def wrapper(*args, **kwargs):
                # Check if lock is valid
                if self._lock:
                    with self._lock:
                        return attr(*args, **kwargs)
                else:
                    return attr(*args, **kwargs)
            return wrapper
        
        # If it's a property, return it as is
        return attr

class MeetInterviewOrchestrator:
    def __init__(
        self,
        session_manager: MeetSessionManager,
        interview_service: InterviewService,
        stt_service: STTService,
        audio_handler: AudioHandler
    ):
        self.session_mgr = session_manager
        self.interview_svc = interview_service
        self.stt_service = stt_service
        self.audio_handler = audio_handler

        # Initialize sub-components
        self.state_mgr = InterviewStateManager(session_manager.db)
        self.response_handler = InterviewResponseHandler(
            interview_service, self.audio_handler, self.stt_service
        )

        self.liveness_svc = LivenessChallengeService()
        self.video_analyzer = VideoIntegrityAnalyzer()
        
        # Participant monitoring
        self.participant_monitor: Optional[ParticipantMonitor] = None
        
        # NEW: Extracted handlers for cleaner code
        self.malpractice_handler = MalpracticeHandler(
            session_manager, interview_service, audio_handler
        )
        self.integrity_handler = IntegrityHandler(
            session_manager, interview_service, audio_handler, self.video_analyzer
        )
        

    async def conduct_interview(
        self,
        session_id: str,
        interview_duration_minutes: int = InterviewTiming.DEFAULT_DURATION_MINUTES,
    ) -> Dict[str, Any]:
        logger.info(f"Starting orchestration | Session: {session_id}")
        
        state = self.state_mgr.load_or_init_state(session_id)
        duration_seconds = interview_duration_minutes * 60
        transcript_log = []
        
        try:
            # Get session with ThreadSafe Proxy
            session = self._get_interview_session(session_id)
            
            # Start monitoring
            self._start_participant_monitoring(session)
            
            #PHASE 1: GREETING
            if state.phase == InterviewPhase.INITIALIZING or state.phase == InterviewPhase.GREETING:
                if not state.is_resumed: 
                    self.state_mgr.advance_phase(state, InterviewPhase.GREETING)
                
                if not await self._run_greeting(session, state):
                    # --- FIX: Return the build response instead of None ---
                    return self._build_final_response(session_id, state, transcript_log) 

                # Only now do we advance
                self.state_mgr.advance_phase(state, InterviewPhase.INTRODUCTION)

            #PHASE 2: INTRODUCTION
            if state.phase == InterviewPhase.INTRODUCTION:
                if await self._run_introduction(session, state):
                    self.state_mgr.advance_phase(state, InterviewPhase.INTERVIEW_LOOP)

            #PHASE 3: MAIN LOOP
            if state.phase == InterviewPhase.INTERVIEW_LOOP:
                result = await self._run_interview_loop(session, state, duration_seconds)
                transcript_log = result.get('transcript_log', [])
                
                # Only advance to CONCLUSION if NOT stopped forcibly
                if not session.stop_event.is_set():
                    self.state_mgr.advance_phase(state, InterviewPhase.CONCLUSION)

            #PHASE 4: CONCLUSION
            if state.phase == InterviewPhase.CONCLUSION and not session.stop_event.is_set():
                logger.info("--- Phase: CONCLUSION ---")
                await self._run_conclusion(session, state)

        except Exception as e:
            logger.error(f"Fatal error in orchestration: {e}", exc_info=True)
            if session and session.stop_event: session.stop_event.set()
        
        finally:
            await self._run_cleanup(session, state)
            self.state_mgr.advance_phase(state, InterviewPhase.COMPLETED)
        
        return self._build_final_response(session_id, state, transcript_log)

    # =========================================================================
    # PARTICIPANT MONITORING
    # =========================================================================
    def _start_participant_monitoring(self, session):
        try:
            self.participant_monitor = ParticipantMonitor(
                session_id=session.session_id,
                meet_controller=session.meet, 
                stop_event=session.stop_event,
                bot_name="AI Bot",  # Ensure this matches your join_meeting name
                on_violation=lambda count, v_type, names: self.malpractice_handler.handle_violation(
                    session, count, v_type, names
                )
            )
            self.participant_monitor.start_monitoring()
            logger.info("Participant monitoring enabled (Smart Detection)")
        except Exception as e:
            logger.error(f"Failed to start participant monitor: {e}")

    # =========================================================================
    # PHASE RUNNERS
    # =========================================================================


    async def _run_greeting(self, session: InterviewSession, state: InterviewState) -> bool:
        logger.info(f"--- Phase: {state.phase} ---")
        greeting = self.interview_svc.generate_initial_greeting(session.session_id)
        
        while True:
            if session.stop_event.is_set():
                if self.malpractice_processing.is_set():
                    logger.info("Greeting aborted due to malpractice")
                return False

            await asyncio.to_thread(session.meet.enable_microphone)
            await asyncio.sleep(InterviewTiming.MIC_TOGGLE_DELAY_SEC)
            
            success = await self._play_text_with_cache(
                greeting, 
                StaticMessages.CACHE_KEY_INTRO_GREETING, 
                session, 
                state.turn_count
            )
            
            if not success:
                if session.stop_event.is_set() and self.malpractice_processing.is_set():
                    logger.info("Greeting interrupted by malpractice detection")
                    return False
                
                logger.warning("Greeting playback failed or interrupted")
                if session.meet.get_participant_count() < 2:
                    if await self._wait_for_rejoin(session):
                        await asyncio.sleep(2)
                        continue
                    else:
                        return False
                return False
            
            self.state_mgr.update_turn_count(state, state.turn_count + 1)
            return True

    async def _run_introduction(self, session: InterviewSession, state: InterviewState) -> bool:
        logger.info(f"--- Phase: {state.phase} ---")
        
        for attempt in range(1, InterviewTiming.MAX_INTRO_ATTEMPTS + 1):
            if session.stop_event.is_set(): return False
            
            response = await self._record_response(session, state.turn_count, is_follow_up=False)
            
            if session.stop_event.is_set(): return False
            
            if response.transcript and response.transcript != "[No response]":
                logger.info("Valid introduction received")
                self.state_mgr.update_turn_count(state, response.turn_count + 1)
                self._log_transcript(session.session_id, response, session.candidate_id)
                await asyncio.to_thread(session.meet.disable_microphone)
                return True
            
            logger.warning("Invalid intro. Reprompting...")
            self.state_mgr.update_turn_count(state, state.turn_count + 1)
            
            await asyncio.to_thread(session.meet.enable_microphone)
            await self._play_text_with_cache(
                StaticMessages.INTRO_REPROMPT, StaticMessages.CACHE_KEY_INTRO_REPROMPT, session, state.turn_count
            )
            self.state_mgr.update_turn_count(state, state.turn_count + 1)

        return True

    async def _run_interview_loop(self, session: InterviewSession, 
                                  state: InterviewState, 
                                  duration_seconds: int) -> Dict[str, Any]:
        logger.info(f"--- Phase: {state.phase} ---")
        transcript_log = []
        has_done_spot_check = False
        
        # Randomize liveness check turn (between turn 2 and 5)
        liveness_check_turn = random.randint(2, 5)
        logger.info(f"Liveness check scheduled for turn {liveness_check_turn}")
        
        while True:
            if await self._should_terminate(session, state, duration_seconds): 
                break
            
            if not await self._wait_for_rejoin(session):
                self.malpractice_handler.set_termination_reason(session.session_id, "candidate_disconnected")
                break

            should_trigger_spot_check = False
            
            # RANDOMIZED: Trigger at the randomly selected turn
            if not has_done_spot_check and state.turn_count >= liveness_check_turn:
                should_trigger_spot_check = True
            
            # Additional override for flagged integrity issues
            if "fake_camera_frozen" in session.malpractice_flags:
                should_trigger_spot_check = True

            if should_trigger_spot_check:
                logger.info(f"Triggering Liveness Spot Check at Turn {state.turn_count} (scheduled for {liveness_check_turn})...")
                success = await self._perform_spot_check(session, state)
                
                if not success:
                    logger.warning("Spot check failed. Terminating session.")
                    self.malpractice_handler.set_termination_reason(session.session_id, "mid_interview_liveness_failed")
                    return {'status': 'terminated_liveness_fail', 'transcript_log': transcript_log}
                
                has_done_spot_check = True
                session.malpractice_flags.clear() 

            # Run integrity check in background (don't block conversation)
            asyncio.create_task(self._check_integrity_async(session))

            # PRIORITY 1: Conversation workflow (record → STT → Gemini → TTS)

            success, new_turn, gen_duration = await self._ask_question(session, state.turn_count)
            
            action = await self._handle_generation_delay_or_failure(
                session, state, gen_duration, success
            )
            if action == "abort": break
            elif action == "retry": continue

            self.state_mgr.mark_question_asked(state, new_turn)
            
            response = await self._record_response(session, state.turn_count, is_follow_up=False)
            
            if session.stop_event.is_set(): break 

            # Run integrity check in background (don't block response processing)
            asyncio.create_task(self._check_integrity_async(session))

            result = await self.response_handler.handle_response(
                session, state, response, self._record_response
            )
            
            self.state_mgr.update_turn_count(state, result.final_response.turn_count + 1)
            
            if not result.proceed:
                continue

            if result.final_response.transcript and result.final_response.transcript != "[No response]":
                self._log_transcript(session.session_id, result.final_response, session.candidate_id)
                transcript_log.append({
                    "role": "user", 
                    "content": result.final_response.transcript,
                    "turn": result.final_response.turn_count
                })
                self.interview_svc.transcript_manager._update_transcript_immediate(
                    session.session_id, result.final_response.transcript
                )
                await asyncio.sleep(InterviewTiming.TRANSCRIPT_PROPAGATION_DELAY_SEC)

        return {'transcript_log': transcript_log}

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    async def _perform_spot_check(self, session: InterviewSession, state: InterviewState) -> bool:
        interruption_text = (
            "Apologies for the interruption. "
            "Our system requires a quick routine security check before we proceed. "
            "Please look to your left."
        )
        
        await self._play_text_with_cache(
            interruption_text, 
            "spot_check_interrupt_look_left", 
            session, 
            state.turn_count
        )

        challenge_type = "look_left" 
        await asyncio.sleep(1.5) 
        
        snapshot_bytes = self.session_mgr.capture_snapshot_now(session.session_id)
        
        if not snapshot_bytes:
            logger.warning("Spot check failed: Could not capture snapshot.")
            return False

        passed = self.liveness_svc.verify_challenge(snapshot_bytes, challenge_type)
        
        if passed:
            logger.info("Spot Check PASSED.")
            await self._play_text_with_cache(
                "Thank you. Let's continue.", "spot_check_success", session, state.turn_count
            )
            return True
        else:
            logger.warning("Spot Check FAILED (Attempt 1). Retrying...")
            await self._play_text_with_cache(
                "I couldn't verify that. Please look to your left clearly.", "spot_check_retry", session, state.turn_count
            )
            await asyncio.sleep(2.5)
            
            snapshot_bytes_retry = self.session_mgr.capture_snapshot_now(session.session_id)
            passed_retry = False
            if snapshot_bytes_retry:
                passed_retry = self.liveness_svc.verify_challenge(snapshot_bytes_retry, challenge_type)
            
            if passed_retry:
                logger.info("Spot Check PASSED (Attempt 2).")
                await self._play_text_with_cache("Thank you.", "spot_check_success", session, state.turn_count)
                return True
                
            logger.error("Spot Check FAILED Final.")
            await self._play_text_with_cache(
                "I am unable to verify your video feed. Ending the session.", "spot_check_fail", session, state.turn_count
            )
            return False

    async def _ask_question(self, session: InterviewSession, turn_count: int) -> Tuple[bool, int, float]:
        start_ts = time.time()
        gemini_task = asyncio.create_task(asyncio.to_thread(
            self.interview_svc.stream_interview_turn, session.session_id, turn_count, session.candidate_id
        ))
        
        await asyncio.to_thread(session.meet.enable_microphone)
        await asyncio.sleep(InterviewTiming.MIC_TOGGLE_DELAY_SEC)
        
        audio_stream = await gemini_task
        duration = time.time() - start_ts
        
        if not audio_stream: 
            return False, turn_count + 1, duration

        logger.debug("Starting audio playback...")
        success = await asyncio.to_thread(
            self.audio_handler.play_audio_stream, audio_stream, session.meet, session.stop_event
        )
        return success, turn_count + 1, duration

    async def _handle_generation_delay_or_failure(
        self, session: InterviewSession, state: InterviewState, duration: float, success: bool
    ) -> str:
        if not success:
            state.consecutive_error_count += 1
            if state.consecutive_error_count >= 3:
                await self._play_text_with_cache(ErrorMessages.TECHNICAL_DIFFICULTIES_EXIT, "error_tech_abort", session, state.turn_count)
                return "abort"
            await self._play_text_with_cache(ErrorMessages.CONNECTION_GLITCH, "error_glitch", session, state.turn_count)
            return "retry"

        if state.consecutive_error_count > 0: state.consecutive_error_count = 0
        if duration > 8.0:
            await self._play_text_with_cache(ErrorMessages.DELAY_APOLOGY, "warn_delay", session, state.turn_count)
        return "continue"

    async def _record_response(self, session: InterviewSession, turn_count: int, is_follow_up: bool) -> ResponseData:
        # Callback for interim transcripts - allows Gemini to see partial input early
        def on_interim(text):
            self.interview_svc.transcript_manager.update_pending_transcript(session.session_id, text)
        
        start_time, transcript = await self.stt_service._record_and_process_stt_streaming(
            session.session_id, turn_count, session.candidate_id, is_follow_up,
            on_interim_transcript=on_interim
        )
        end_time = datetime.now()
        await asyncio.to_thread(session.meet.disable_microphone)
        
        audio_path = get_user_audio_path_for_stt(session.session_id, turn_count, session.candidate_id, is_follow_up)
        return ResponseData(transcript, audio_path, start_time, end_time, turn_count, is_follow_up)

    async def _play_text_with_cache(self, text: str, cache_key: str, session: InterviewSession, turn_count: int) -> bool:
        if session.stop_event.is_set(): return False
        path = self.interview_svc.get_static_audio_path(text, cache_key)
        if not path: return False
        
        success = await asyncio.to_thread(self.audio_handler.play_wav_file, path, session.meet, session.stop_event)
        return success

    def _get_interview_session(self, session_id: str) -> InterviewSession:
        session_data = self.session_mgr.get_session(session_id)
        if not session_data or not session_data.get('controller'):
            raise ValueError(f"Session {session_id} invalid")
            
        if 'malpractice_flags' not in session_data:
            session_data['malpractice_flags'] = set()
        
        raw_controller = session_data.get('controller')
        session_lock = session_data.get('lock')
        safe_controller = ThreadSafeControllerProxy(raw_controller, session_lock)

        return InterviewSession(
            session_id, 
            session_data.get('candidate_id'), 
            safe_controller,
            session_data.get('stop_interview'),
            session_data['malpractice_flags'] 
        )

    def _log_transcript(self, session_id, response, candidate_id):
        self.interview_svc.process_and_log_transcript(
            session_id, str(response.audio_path), response.transcript,
            response.turn_count, candidate_id, response.start_time, response.end_time,
            response.is_follow_up
        )

    async def _check_integrity_async(self, session: InterviewSession):
        """Run integrity check in background (low priority) - doesn't block conversation."""
        try:
            await asyncio.to_thread(self.integrity_handler.check_video_integrity, session)
        except Exception as e:
            logger.debug(f"Background integrity check failed: {e}")

    async def _should_terminate(self, session, state, duration):
        if session.stop_event.is_set(): return True
        elapsed = time.time() - state.start_time
        if elapsed > duration:
            self.malpractice_handler.set_termination_reason(session.session_id, TerminationReason.TIME_LIMIT_REACHED)
            return True
        return False

    async def _wait_for_rejoin(self, session: InterviewSession) -> bool:
        MAX_WAIT_SECONDS = 180
        POLL_INTERVAL = 2
        
        if session.meet.get_participant_count() >= 2: return True
        logger.warning(f" Candidate disconnected. Waiting {MAX_WAIT_SECONDS}s")
        try: session.meet.send_chat_message("Connection lost. I am waiting here for you to rejoin.")
        except Exception: pass

        start_time = time.time()
        while time.time() - start_time < MAX_WAIT_SECONDS:
            if session.stop_event.is_set(): return False
            try:
                if session.meet.get_participant_count() >= 2:
                    # Track this reconnection
                    reconnect_count = self.session_mgr.increment_reconnection_count(session.session_id)
                    logger.info(f"Candidate rejoined! (Reconnection #{reconnect_count})")
                    
                    await asyncio.sleep(4.0)
                    await asyncio.to_thread(session.meet.enable_microphone)
                    await asyncio.sleep(InterviewTiming.MIC_TOGGLE_DELAY_SEC)
                    await self._play_text_with_cache(StaticMessages.RESUME_GREETING, StaticMessages.CACHE_KEY_RESUME, session, 0)
                    await asyncio.to_thread(session.meet.disable_microphone)
                    return True
            except Exception: pass
            await asyncio.sleep(POLL_INTERVAL)
        return False 
    
    async def _run_conclusion(self, session: InterviewSession, state: InterviewState):
        logger.info("Playing outro message...")
        await asyncio.to_thread(session.meet.enable_microphone)
        await asyncio.sleep(InterviewTiming.MIC_TOGGLE_DELAY_SEC)
        await self._play_text_with_cache(StaticMessages.OUTRO_MESSAGE, StaticMessages.CACHE_KEY_OUTRO, session, state.turn_count)
        await asyncio.sleep(2.0)

    async def _run_cleanup(self, session, state):
        if self.malpractice_handler.processing.is_set():
            for _ in range(20):
                if not self.malpractice_handler.processing.is_set(): break
                await asyncio.sleep(1)
        if self.participant_monitor:
            self.participant_monitor.stop_monitoring()
            self.participant_monitor = None
        
    def _build_final_response(self, session_id, state, logs):
        final_response = {
            "status": SessionStatus.COMPLETED,
            "session_id": session_id,
            "questions_asked": state.questions_asked_count,
            "final_transcript_summary": logs
        }
        if self.participant_monitor:
            final_response['monitoring_stats'] = self.participant_monitor.get_status()
        return final_response