# app/services/stt_service.py
import logging
import os
import time
import asyncio
import sounddevice as sd
import numpy as np
from typing import Optional, Tuple, Callable
from datetime import datetime
import queue
import threading
import soundfile as sf
import io
from pathlib import Path
from dataclasses import dataclass, field

# V1 imports
try:
    from google.cloud import speech_v1
    V1_AVAILABLE = True
except ImportError:
    V1_AVAILABLE = False

# V2 imports
try:
    from google.cloud.speech_v2 import SpeechClient
    from google.cloud.speech_v2.types import cloud_speech
    from google.cloud.speech_v2.services.speech.transports import SpeechGrpcTransport
    from google.api_core import exceptions as google_exceptions
    import google.auth
    from google.auth.transport.grpc import secure_authorized_channel
    from google.auth.transport.requests import Request
    V2_AVAILABLE = True
except ImportError:
    V2_AVAILABLE = False

from app.agents.interview.infrastructure.browser.meet_session_manager import MeetSessionManager
from app.agents.interview.utils.audio_file_utils import get_user_audio_path_for_stt, save_audio_file
from app.agents.interview.config.constants import AudioConfig, ServiceConfig
from app.agents.interview.services.audio.linux_audio import (
    configure_chromium_virtual_source,
    setup_linux_audio,
)
from app.agents.interview.core.session_error_tracker import record_session_error
from app.core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class RecordingState:
    recording_start: datetime
    recording_started_at: float = field(default_factory=time.time)
    last_transcript_at: Optional[float] = None
    has_transcript: bool = False
    last_speech_volume_at: Optional[float] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def mark_transcript(self):
        with self.lock:
            self.has_transcript = True
            self.last_transcript_at = time.time()

    def mark_speech_volume(self):
        with self.lock:
            self.last_speech_volume_at = time.time()

    def snapshot(self):
        with self.lock:
            return {
                "recording_started_at": self.recording_started_at,
                "last_transcript_at": self.last_transcript_at,
                "has_transcript": self.has_transcript,
                "last_speech_volume_at": self.last_speech_volume_at,
            }

class STTService:
    def __init__(self, session_manager: MeetSessionManager):
        self.session_mgr = session_manager
        self.api_version = settings.SPEECH_API_VERSION

        if self.api_version not in ["v1", "v2"]:
            logger.error(f"Invalid API version: {self.api_version}, defaulting to v2")
            self.api_version = "v2"
        
        self.speech_client = None
        self.recognizer = None
        
        logger.info(f"STT Service using Speech API: {self.api_version.upper()}")
        
        if self.api_version == "v2":
            self._init_v2_client()
        else:
            self._init_v1_client()
        
        self.virtual_input = self._find_recording_device()
        if not getattr(self, 'samplerate', None):
            self.samplerate = AudioConfig.SAMPLE_RATE_24K

    def _find_recording_device(self) -> Optional[int]:
        try:
            target_name = AudioConfig.RECORDING_DEVICE_NAME.lower()
            devices = sd.query_devices()
            preferred_hostapis = ['Windows WASAPI', 'Windows DirectSound', 'MME']
            for api in preferred_hostapis:
                for d in devices:
                    if d['max_input_channels'] > 0 and target_name in d['name'].lower():
                        host_api_name = sd.query_hostapis(d['hostapi'])['name']
                        if host_api_name == api:
                            self.samplerate = int(d['default_samplerate'])
                            return d['index']
            for d in devices:
                if d['max_input_channels'] > 0 and target_name in d['name'].lower():
                    self.samplerate = int(d['default_samplerate'])
                    return d['index']
                    
            if os.name != 'nt':
                # Fallback to the explicit PulseAudio device on Linux
                # since we set PULSE_SOURCE in the environment
                for d in devices:
                    if d['name'] == 'pulse' and d['max_input_channels'] > 0:
                        logger.info("Falling back to PulseAudio device for STT recording")
                        self.samplerate = int(d['default_samplerate']) or 48000
                        return d['index']
            return None
        except Exception as e:
            logger.error(f"Error finding STT audio device: {e}")
            return None

    def ensure_recording_device(self) -> bool:
        """Refresh the STT device after a Linux audio-server restart."""
        if os.name != "nt":
            if not setup_linux_audio(max_retries=1, retry_delay_seconds=0):
                logger.error("[STT] PulseAudio/PipeWire is unavailable before recording")
                return False
            if not configure_chromium_virtual_source():
                logger.error("[STT] Chromium virtual source is unavailable before recording")
                return False

        device = self._find_recording_device()
        if device is None:
            logger.error("[STT] No recording device is available")
            return False
        self.virtual_input = device
        return True

    def _init_v1_client(self):
        if not V1_AVAILABLE: return
        try:
            self.speech_client = speech_v1.SpeechClient()
        except Exception as e:
            logger.error(f"Failed to initialize Speech V1: {e}")

    def _init_v2_client(self):
        if not V2_AVAILABLE: return
        try:
            self.project_id = settings.GOOGLE_CLOUD_PROJECT
            self.location = settings.GOOGLE_CLOUD_REGION
            api_endpoint = f"{self.location}-speech.googleapis.com"
            keepalive_options = [('grpc.keepalive_time_ms', ServiceConfig.GRPC_KEEPALIVE_TIME_MS), ('grpc.keepalive_timeout_ms', ServiceConfig.GRPC_KEEPALIVE_TIMEOUT_MS), ('grpc.keepalive_permit_without_calls', 1), ('grpc.http2.max_pings_without_data', 0)]
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            credentials, _ = google.auth.default(scopes=scopes)
            channel = secure_authorized_channel(credentials, request=Request(), target=api_endpoint, options=keepalive_options)
            transport = SpeechGrpcTransport(channel=channel)
            self.speech_client = SpeechClient(transport=transport)
            self.recognizer = f"projects/{self.project_id}/locations/{self.location}/recognizers/_"
        except Exception as e:
            logger.error(f"Failed to initialize Speech V2: {e}")

    async def _record_and_process_stt_streaming(self, session_id: str, turn_count: int, is_follow_up: bool = False, on_interim_transcript: Callable[[str], None] = None) -> Tuple[Optional[datetime], str]:
        if not await asyncio.to_thread(self.ensure_recording_device):
            return None, "[STT unavailable]"
        if self.api_version == "v2":
            return await asyncio.to_thread(self._process_with_v2, session_id, turn_count, is_follow_up, on_interim_transcript)
        else:
            return await asyncio.to_thread(self._process_with_v1, session_id, turn_count, is_follow_up)

    def _process_with_v1(self, session_id: str, turn_count: int, is_follow_up: bool) -> Tuple[Optional[datetime], str]:
        if not self.speech_client or not V1_AVAILABLE: return None, "[Speech service unavailable]"
        audio_queue = queue.Queue(); recorded_chunks = []; transcript_parts = []
        try:
            session = self.session_mgr.get_session(session_id)
            if not session or (session.get('stop_interview') and session.get('stop_interview').is_set()): return None, "[Error]"
            stop_event = session.get('stop_interview'); input_device = self.virtual_input if self.virtual_input is not None else sd.default.device[0]
            def audio_callback(indata, frames, time, status):
                audio_queue.put((indata * 32767).astype(np.int16).tobytes())
                recorded_chunks.append(indata.copy())
            def request_generator():
                while True:
                    chunk = audio_queue.get()
                    if chunk is None: break
                    yield speech_v1.StreamingRecognizeRequest(audio_content=chunk)
            def stt_processor():
                try:
                    config = speech_v1.RecognitionConfig(encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16, sample_rate_hertz=self.samplerate, language_code=ServiceConfig.STT_LANGUAGE_CODE, enable_automatic_punctuation=True, model=ServiceConfig.STT_MODEL_V1)
                    responses = self.speech_client.streaming_recognize(config=speech_v1.StreamingRecognitionConfig(config=config, interim_results=True), requests=request_generator())
                    for response in responses:
                        if response.results and response.results[0].is_final:
                            if response.results[0].alternatives:
                                transcript_parts.append(response.results[0].alternatives[0].transcript)
                                recording_state.mark_transcript()
                except Exception as error:
                    logger.error("[STT] Speech V1 streaming failed: %s", error, exc_info=True)
                    record_session_error(session_id, "stt_service", str(error), type(error).__name__)
            stream = sd.InputStream(samplerate=self.samplerate, device=input_device, channels=1, callback=audio_callback, dtype='float32')
            stream.start(); recording_start = datetime.now()
            recording_state = RecordingState(recording_start=recording_start)
            stt_thread = threading.Thread(target=stt_processor, daemon=True); stt_thread.start()
            self._monitor_recording(recorded_chunks, stop_event, recording_start, session_id, recording_state)
            stream.stop(); stream.close(); audio_queue.put(None); stt_thread.join(timeout=10)
            if recorded_chunks: threading.Thread(target=self._save_recorded_audio, args=(recorded_chunks, session_id, turn_count, is_follow_up), daemon=True).start()
            final_transcript = " ".join(transcript_parts).strip()
            return recording_start, final_transcript if final_transcript else "[No response]"
        except Exception as error:
            logger.error("[STT] V1 recording failed: %s", error, exc_info=True)
            return None, "[STT failed]"

    def _process_with_v2(self, session_id: str, turn_count: int, is_follow_up: bool, on_interim_transcript: Callable[[str], None] = None) -> Tuple[Optional[datetime], str]:
        if not self.speech_client or not self.recognizer: return None, "[Speech service unavailable]"
        audio_queue = queue.Queue(); recorded_chunks = []; transcript_parts = []
        try:
            session = self.session_mgr.get_session(session_id)
            if not session or (session.get('stop_interview') and session.get('stop_interview').is_set()): return None, "[Error]"
            stop_event = session.get('stop_interview'); input_device = self.virtual_input if self.virtual_input is not None else sd.default.device[0]
            def audio_callback(indata, frames, time, status):
                audio_queue.put((indata * 32767).astype(np.int16).tobytes())
                recorded_chunks.append(indata.copy())
            def request_generator():
                config = cloud_speech.RecognitionConfig(explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16, sample_rate_hertz=self.samplerate, audio_channel_count=1), language_codes=[ServiceConfig.STT_LANGUAGE_CODE], model=ServiceConfig.STT_MODEL_V2, features=cloud_speech.RecognitionFeatures(enable_automatic_punctuation=True))
                yield cloud_speech.StreamingRecognizeRequest(recognizer=self.recognizer, streaming_config=cloud_speech.StreamingRecognitionConfig(config=config, streaming_features=cloud_speech.StreamingRecognitionFeatures(interim_results=True, enable_voice_activity_events=True)))
                while True:
                    chunk = audio_queue.get()
                    if chunk is None: break
                    yield cloud_speech.StreamingRecognizeRequest(audio=chunk)
            def stt_processor():
                try:
                    responses = self.speech_client.streaming_recognize(requests=request_generator())
                    for response in responses:
                        if response.results:
                            for result in response.results:
                                if not result.alternatives:
                                    continue
                                transcript_text = result.alternatives[0].transcript
                                if transcript_text:
                                    recording_state.mark_transcript()
                                if not result.is_final and transcript_text and on_interim_transcript:
                                    try: on_interim_transcript(transcript_text)
                                    except Exception: pass
                                if result.is_final and result.alternatives:
                                    transcript_parts.append(transcript_text)
                except Exception as error:
                    logger.error("[STT] Speech V2 streaming failed: %s", error, exc_info=True)
                    record_session_error(session_id, "stt_service", str(error), type(error).__name__)
            stream = sd.InputStream(samplerate=self.samplerate, device=input_device, channels=1, callback=audio_callback, dtype='float32')
            stream.start(); recording_start = datetime.now()
            recording_state = RecordingState(recording_start=recording_start)
            stt_thread = threading.Thread(target=stt_processor, daemon=True); stt_thread.start()
            self._monitor_recording(recorded_chunks, stop_event, recording_start, session_id, recording_state)
            stream.stop(); stream.close(); audio_queue.put(None); stt_thread.join(timeout=10)
            if recorded_chunks: threading.Thread(target=self._save_recorded_audio, args=(recorded_chunks, session_id, turn_count, is_follow_up), daemon=True).start()
            final_transcript = " ".join(transcript_parts).strip()
            return recording_start, final_transcript if final_transcript else "[No response]"
        except Exception as error:
            logger.error("[STT] V2 recording failed: %s", error, exc_info=True)
            return None, "[STT failed]"

    def _monitor_recording(self, recorded_chunks, stop_event, recording_start, session_id, recording_state: Optional[RecordingState] = None):
        recording_state = recording_state or RecordingState(recording_start=recording_start)
        speech_detected = False; silence_start_time = None; speech_start_time = None
        log_interval = 0
        last_check_time = time.time()
        
        while True:
            time.sleep(0.05)
            if stop_event and stop_event.is_set(): break
            elapsed = (datetime.now() - recording_start).total_seconds()
            if elapsed >= AudioConfig.MAX_RECORDING_DURATION_SEC: break
            current_time = time.time()
            state_snapshot = recording_state.snapshot()
            if (
                not state_snapshot["has_transcript"]
                and not speech_detected
                and (current_time - state_snapshot["recording_started_at"]) >= AudioConfig.INITIAL_SPEECH_TIMEOUT_SEC
            ):
                logger.info("[STT] Initial speech timeout reached. Stopping recording.")
                break
            if state_snapshot["has_transcript"]:
                last_activity_at = max(
                    state_snapshot["last_transcript_at"] or state_snapshot["recording_started_at"],
                    state_snapshot["last_speech_volume_at"] or state_snapshot["recording_started_at"],
                )
                if (current_time - last_activity_at) >= AudioConfig.TRANSCRIPT_IDLE_TIMEOUT_SEC:
                    logger.info("[STT] Transcript idle timeout reached. Stopping recording.")
                    break
            
            # Smart Early Disconnect Detection (Check every 2 seconds)
            if current_time - last_check_time >= 2.0:
                last_check_time = current_time
                try:
                    # ParticipantMonitor updates `malpractice_flags` via handlers, but the fastest
                    # way without async blocking is just to check if the session is still active
                    session_data = self.session_mgr.get_session(session_id)
                    if session_data and 'stop_interview' in session_data:
                        if session_data['stop_interview'].is_set():
                            logger.info(f"[STT] Detected stop signal for {session_id}, aborting STT recording early.")
                            break
                        
                        # Alternatively check for candidate disconnected via active loop in orchestrator
                        # but if stop_event wasn't set, we can check participant count if we have the async loop
                        controller = session_data.get('controller')
                        if controller:
                            import asyncio
                            try:
                                loop = asyncio.get_running_loop()
                            except RuntimeError:
                                loop = None
                            
                            if loop is None:
                                # We're in a separate thread. We can't easily await the controller's async method.
                                # However, if the Orchestrator loop triggers malpractice, the stop_event will be set.
                                pass
                except Exception as e:
                    logger.debug(f"[STT] Disconnect check error: {e}")

            if len(recorded_chunks) > 5:
                # Log volume roughly every second
                log_interval += 1
                volume = np.sqrt(np.mean(np.concatenate(recorded_chunks[-5:], axis=0)**2))
                if log_interval % 20 == 0:
                    logger.info(f"[STT] Current audio volume: {volume:.5f} (Threshold: {AudioConfig.VOLUME_THRESHOLD})")
                
                if volume > AudioConfig.VOLUME_THRESHOLD:
                    recording_state.mark_speech_volume()
                    silence_start_time = None
                    if not speech_detected:
                        if speech_start_time is None: speech_start_time = time.time()
                        if (time.time() - speech_start_time) >= AudioConfig.MIN_SPEECH_DURATION_SEC: 
                            speech_detected = True
                            logger.info("[STT] Speech detected.")
                elif speech_detected:
                    if silence_start_time is None: silence_start_time = time.time()
                    if elapsed >= AudioConfig.MIN_RECORDING_SEC and (time.time() - silence_start_time) > AudioConfig.SILENCE_THRESHOLD_SEC: 
                        logger.info("[STT] Silence threshold reached. Stopping recording.")
                        break
                else: speech_start_time = None

    def _save_recorded_audio(self, recorded_chunks: list, session_id: str, turn_count: int, is_follow_up: bool):
        try:
            if not recorded_chunks: return
            recording_data = np.concatenate(recorded_chunks, axis=0)
            audio_path = get_user_audio_path_for_stt(session_id, turn_count, is_follow_up)
            save_audio_file(recording_data, audio_path, self.samplerate)
        except Exception as e:
            logger.error(f"Error saving audio: {e}")
