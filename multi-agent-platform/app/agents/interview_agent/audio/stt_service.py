
# app/services/interview/audio/stt_service.py
import logging
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

from app.agents.interview_agent.audio.audio_handler import AudioHandler

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

from app.agents.interview_agent.selenium.meet_session_manager import MeetSessionManager
from app.core.ports.session_repository import SessionRepository
from app.agents.interview_agent.utils.audio_file_utils import get_user_audio_path_for_stt, save_audio_file

from app.config.settings import Config
from app.config.constants import AudioConfig, ServiceConfig

logger = logging.getLogger(__name__)


class STTService:
    def __init__(
        self,
        session_manager: MeetSessionManager,
        db_handler: SessionRepository
    ):
        self.session_mgr = session_manager
        self.db_handler = db_handler
        self.api_version = Config.SPEECH_API_VERSION

        if self.api_version not in ["v1", "v2"]:
            logger.error(f"Invalid API version: {self.api_version}, defaulting to v2")
            self.api_version = "v2"
        
        logger.info(f"STT Service using Speech API: {self.api_version.upper()}")
        
        if self.api_version == "v2":
            self._init_v2_client()
        else:
            self._init_v1_client()
        
        self.virtual_input = self._find_recording_device()
        self.samplerate = AudioConfig.SAMPLE_RATE_24K

    def _find_recording_device(self) -> Optional[int]:
        try:
            devices = sd.query_devices()
            device_index = next(
                (d['index'] for d in devices
                 if AudioConfig.RECORDING_DEVICE_NAME in d['name']
                 and d['max_input_channels'] > 0),
                None
            )
            if device_index is not None:
                logger.info(f"[STTService] Found VB-Audio Recording: {device_index}")
            else:
                logger.warning("[STTService] VB-Audio Recording device not found")
            return device_index
        except Exception as e:
            logger.error(f"Error finding STT audio device: {e}")
            return None

    def _init_v1_client(self):
        if not V1_AVAILABLE: return
        try:
            self.speech_client = speech_v1.SpeechClient()
            logger.info(" Speech V1 Client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Speech V1: {e}")

    def _init_v2_client(self):
        if not V2_AVAILABLE: return
        try:
            self.project_id = Config.GOOGLE_CLOUD_PROJECT
            self.location = Config.GOOGLE_CLOUD_LOCATION
            api_endpoint = f"{self.location}-speech.googleapis.com"
            keepalive_options = [
                ('grpc.keepalive_time_ms', ServiceConfig.GRPC_KEEPALIVE_TIME_MS),
                ('grpc.keepalive_timeout_ms', ServiceConfig.GRPC_KEEPALIVE_TIMEOUT_MS),
                ('grpc.keepalive_permit_without_calls', 1),
                ('grpc.http2.max_pings_without_data', 0),
            ]
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            credentials, _ = google.auth.default(scopes=scopes)
            channel = secure_authorized_channel(credentials, request=Request(), target=api_endpoint, options=keepalive_options)
            transport = SpeechGrpcTransport(channel=channel)
            self.speech_client = SpeechClient(transport=transport)
            self.recognizer = f"projects/{self.project_id}/locations/{self.location}/recognizers/_"
            logger.info(" Speech V2 Client initialized with Chirp 3 & gRPC KeepAlive")
        except Exception as e:
            logger.error(f"Failed to initialize Speech V2: {e}")

    def check_health(self) -> bool:
        if not self.speech_client: return False
        if self.api_version == "v1": return True
        try:
            parent = f"projects/{self.project_id}/locations/{self.location}"
            self.speech_client.list_recognizers(request=cloud_speech.ListRecognizersRequest(parent=parent))
            return True
        except Exception: return False

    async def _record_and_process_stt_streaming(
        self, 
        session_id: str, 
        turn_count: int, 
        candidate_id: str, 
        is_follow_up: bool = False,
        on_interim_transcript: Callable[[str], None] = None
    ) -> Tuple[Optional[datetime], str]:
        loop = asyncio.get_running_loop()
        if self.api_version == "v2":
            return await asyncio.to_thread(self._process_with_v2, session_id, turn_count, candidate_id, is_follow_up, on_interim_transcript, loop)
        else:
            return await asyncio.to_thread(self._process_with_v1, session_id, turn_count, candidate_id, is_follow_up, loop)

    def _process_with_v1(self, session_id: str, turn_count: int, candidate_id: str, is_follow_up: bool, loop: asyncio.AbstractEventLoop) -> Tuple[Optional[datetime], str]:
        if not self.speech_client or not V1_AVAILABLE: return None, "[Speech service unavailable]"
        
        audio_queue = queue.Queue(); recorded_chunks = []; transcript_parts = []
        try:
            session = self.session_mgr.get_session(session_id)
            if not session or (session.get('stop_interview') and session.get('stop_interview').is_set()): return None, "[Error]"
            
            stop_event = session.get('stop_interview')
            input_device = self.virtual_input or sd.default.device[0]
            
            def audio_callback(indata, frames, time, status):
                audio_bytes = (indata * 32767).astype(np.int16).tobytes()
                audio_queue.put(audio_bytes)
                recorded_chunks.append(indata.copy())
            
            def request_generator():
                while True:
                    chunk = audio_queue.get()
                    if chunk is None: break
                    yield speech_v1.StreamingRecognizeRequest(audio_content=chunk)
            
            def stt_processor():
                try:
                    config = speech_v1.RecognitionConfig(
                        encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                        sample_rate_hertz=self.samplerate,
                        language_code=ServiceConfig.STT_LANGUAGE_CODE,
                        enable_automatic_punctuation=True,
                        model=ServiceConfig.STT_MODEL_V1
                    )
                    responses = self.speech_client.streaming_recognize(
                        config=speech_v1.StreamingRecognitionConfig(config=config, interim_results=True),
                        requests=request_generator()
                    )
                    for response in responses:
                        if response.results and response.results[0].is_final:
                            if response.results[0].alternatives:
                                transcript_parts.append(response.results[0].alternatives[0].transcript)
                except Exception as e:
                    logger.error(f"STT V1 processing error: {e}")
                    if not transcript_parts: transcript_parts.append("[Speech service error]")
            
            stream = sd.InputStream(samplerate=self.samplerate, device=input_device, channels=1, callback=audio_callback, dtype='float32')
            stream.start()
            recording_start = datetime.now()
            stt_thread = threading.Thread(target=stt_processor, daemon=True); stt_thread.start()
            self._monitor_recording(recorded_chunks, session, stop_event, recording_start, loop)
            stream.stop(); stream.close(); audio_queue.put(None); stt_thread.join(timeout=10)
            
            if recorded_chunks:
                self._save_recorded_audio(recorded_chunks, session_id, turn_count, candidate_id, is_follow_up, loop)
            
            final_transcript = " ".join(transcript_parts).strip()
            return recording_start, final_transcript if final_transcript else "[No response]"
        except Exception as e:
            logger.error(f"V1 error: {e}"); return None, "[Error]"

    def _process_with_v2(
        self, 
        session_id: str, 
        turn_count: int, 
        candidate_id: str, 
        is_follow_up: bool,
        on_interim_transcript: Callable[[str], None] = None,
        loop: asyncio.AbstractEventLoop = None
    ) -> Tuple[Optional[datetime], str]:
        if not self.speech_client or not self.recognizer: return None, "[Speech service unavailable]"
        
        audio_queue = queue.Queue(); recorded_chunks = []; transcript_parts = []
        try:
            session = self.session_mgr.get_session(session_id)
            if not session or (session.get('stop_interview') and session.get('stop_interview').is_set()): return None, "[Error]"
            stop_event = session.get('stop_interview')
            input_device = self.virtual_input or sd.default.device[0]
            
            def audio_callback(indata, frames, time, status):
                audio_bytes = (indata * 32767).astype(np.int16).tobytes()
                audio_queue.put(audio_bytes)
                recorded_chunks.append(indata.copy())
            
            def request_generator():
                config = cloud_speech.RecognitionConfig(
                    explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                        encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                        sample_rate_hertz=self.samplerate, audio_channel_count=1
                    ),
                    language_codes=[ServiceConfig.STT_LANGUAGE_CODE], model=ServiceConfig.STT_MODEL_V2,
                    features=cloud_speech.RecognitionFeatures(enable_automatic_punctuation=True)
                )
                yield cloud_speech.StreamingRecognizeRequest(recognizer=self.recognizer, streaming_config=cloud_speech.StreamingRecognitionConfig(config=config, streaming_features=cloud_speech.StreamingRecognitionFeatures(interim_results=True)))
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
                                # Send interim results for early Gemini processing
                                if not result.is_final and result.alternatives and on_interim_transcript:
                                    try:
                                        on_interim_transcript(result.alternatives[0].transcript)
                                    except Exception:
                                        pass  # Don't let callback errors break STT
                                if result.is_final and result.alternatives:
                                    transcript_parts.append(result.alternatives[0].transcript)
                except Exception: pass

            stream = sd.InputStream(samplerate=self.samplerate, device=input_device, channels=1, callback=audio_callback, dtype='float32')
            stream.start()
            recording_start = datetime.now()
            stt_thread = threading.Thread(target=stt_processor, daemon=True); stt_thread.start()
            self._monitor_recording(recorded_chunks, session, stop_event, recording_start, loop)
            stream.stop(); stream.close(); audio_queue.put(None); stt_thread.join(timeout=10)
            
            if recorded_chunks:
                self._save_recorded_audio(recorded_chunks, session_id, turn_count, candidate_id, is_follow_up, loop)
            
            final_transcript = " ".join(transcript_parts).strip()
            return recording_start, final_transcript if final_transcript else "[No response]"
        except Exception as e:
            logger.error(f"V2 error: {e}"); return None, "[Error]"

    # =========================================================================
    # SIMPLIFIED VOICE ACTIVITY DETECTION (VAD)
    # =========================================================================
    def _monitor_recording(self, recorded_chunks, session, stop_event, recording_start, loop: asyncio.AbstractEventLoop = None):
        speech_detected = False
        silence_start_time = None
        
        # Simple fixed thresholds
        MAX_DURATION_SEC = AudioConfig.MAX_RECORDING_DURATION_SEC
        SILENCE_THRESHOLD = AudioConfig.SILENCE_THRESHOLD_SEC
        MIN_RECORDING = AudioConfig.MIN_RECORDING_SEC
        VOLUME_THRESHOLD = AudioConfig.VOLUME_THRESHOLD
        
        while True:
            # 1. Safety Checks
            if not session or (stop_event and stop_event.is_set()): break
            if not self._is_candidate_present(session): break
            
            # 2. Hard Timeout
            elapsed = (datetime.now() - recording_start).total_seconds()
            if elapsed >= MAX_DURATION_SEC:
                logger.info("STT: Max recording duration reached (Hard Limit).")
                break
            
            # 3. Analyze Audio
            if len(recorded_chunks) > 5:
                recent = np.concatenate(recorded_chunks[-5:], axis=0)
                volume = np.sqrt(np.mean(recent**2))
                
                if volume > VOLUME_THRESHOLD:
                    # --- SPEECH DETECTED ---
                    speech_detected = True
                    silence_start_time = None  # Reset silence timer
                
                elif speech_detected:
                    # --- SILENCE AFTER SPEECH ---
                    if silence_start_time is None:
                        silence_start_time = time.time()
                    
                    silence_duration = time.time() - silence_start_time
                    
                    # Only stop if we've recorded for minimum time AND silence exceeded threshold
                    if elapsed >= MIN_RECORDING and silence_duration > SILENCE_THRESHOLD:
                        logger.info(f"STT: Silence ({silence_duration:.2f}s) > {SILENCE_THRESHOLD}s. Stopping.")
                        break

            time.sleep(0.05)  # Poll frequency

    def _is_candidate_present(self, session: dict) -> bool:
        try:
            return session.get('controller').get_participant_count() >= 2
        except Exception: return True

    def _save_recorded_audio(self, recorded_chunks: list, session_id: str, turn_count: int, candidate_id: str, is_follow_up: bool, loop: asyncio.AbstractEventLoop):
        """
        Saves audio to BOTH local disk (for VoiceDetector analysis) AND MongoDB (for long-term storage).
        """
        try:
            if not recorded_chunks: return

            recording_data = np.concatenate(recorded_chunks, axis=0)
            duration = len(recording_data) / self.samplerate
            
            # Save Usage Stats - Async via loop
            if loop:
                asyncio.run_coroutine_threadsafe(
                    self.db_handler.update_stt_usage(session_id, duration), 
                    loop
                )
            
            # 1. Save locally (Required for existing VoiceDetector)
            audio_path = get_user_audio_path_for_stt(session_id, turn_count, candidate_id, is_follow_up)
            save_audio_file(recording_data, audio_path, self.samplerate)
            
            # 2. Save to MongoDB
            buffer = io.BytesIO()
            sf.write(buffer, recording_data, self.samplerate, format='WAV', subtype='PCM_16')
            audio_bytes = buffer.getvalue()
            
            if loop:
                asyncio.run_coroutine_threadsafe(
                    self.db_handler.save_file(
                        filename=audio_path.name, 
                        data=audio_bytes
                    ),
                    loop
                )
            # logger.debug(f"Archived user audio: {audio_path.name}")
            
        except Exception as e:
            logger.error(f"Error saving recorded audio: {e}")
