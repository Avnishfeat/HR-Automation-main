# app/services/stt_service.py
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
from pathlib import Path

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

from app.agents.interview.infrastructure.selenium.meet_session_manager import MeetSessionManager
from app.agents.interview.utils.audio_file_utils import get_user_audio_path_for_stt, save_audio_file
from app.agents.interview.config.constants import AudioConfig, ServiceConfig
from app.core.config import settings

logger = logging.getLogger(__name__)

class STTService:
    def __init__(self, session_manager: MeetSessionManager):
        self.session_mgr = session_manager
        self.api_version = settings.SPEECH_API_VERSION

        if self.api_version not in ["v1", "v2"]:
            logger.error(f"Invalid API version: {self.api_version}, defaulting to v2")
            self.api_version = "v2"
        
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
            return None
        except Exception as e:
            logger.error(f"Error finding STT audio device: {e}")
            return None

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
            stop_event = session.get('stop_interview'); input_device = self.virtual_input or sd.default.device[0]
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
                except Exception: pass
            stream = sd.InputStream(samplerate=self.samplerate, device=input_device, channels=1, callback=audio_callback, dtype='float32')
            stream.start(); recording_start = datetime.now()
            stt_thread = threading.Thread(target=stt_processor, daemon=True); stt_thread.start()
            self._monitor_recording(recorded_chunks, session, stop_event, recording_start)
            stream.stop(); stream.close(); audio_queue.put(None); stt_thread.join(timeout=10)
            if recorded_chunks: threading.Thread(target=self._save_recorded_audio, args=(recorded_chunks, session_id, turn_count, is_follow_up), daemon=True).start()
            final_transcript = " ".join(transcript_parts).strip()
            return recording_start, final_transcript if final_transcript else "[No response]"
        except Exception: return None, "[Error]"

    def _process_with_v2(self, session_id: str, turn_count: int, is_follow_up: bool, on_interim_transcript: Callable[[str], None] = None) -> Tuple[Optional[datetime], str]:
        if not self.speech_client or not self.recognizer: return None, "[Speech service unavailable]"
        audio_queue = queue.Queue(); recorded_chunks = []; transcript_parts = []
        try:
            session = self.session_mgr.get_session(session_id)
            if not session or (session.get('stop_interview') and session.get('stop_interview').is_set()): return None, "[Error]"
            stop_event = session.get('stop_interview'); input_device = self.virtual_input or sd.default.device[0]
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
                                if not result.is_final and result.alternatives and on_interim_transcript:
                                    try: on_interim_transcript(result.alternatives[0].transcript)
                                    except Exception: pass
                                if result.is_final and result.alternatives:
                                    transcript_parts.append(result.alternatives[0].transcript)
                except Exception: pass
            stream = sd.InputStream(samplerate=self.samplerate, device=input_device, channels=1, callback=audio_callback, dtype='float32')
            stream.start(); recording_start = datetime.now()
            stt_thread = threading.Thread(target=stt_processor, daemon=True); stt_thread.start()
            self._monitor_recording(recorded_chunks, session, stop_event, recording_start)
            stream.stop(); stream.close(); audio_queue.put(None); stt_thread.join(timeout=10)
            if recorded_chunks: threading.Thread(target=self._save_recorded_audio, args=(recorded_chunks, session_id, turn_count, is_follow_up), daemon=True).start()
            final_transcript = " ".join(transcript_parts).strip()
            return recording_start, final_transcript if final_transcript else "[No response]"
        except Exception: return None, "[Error]"

    def _monitor_recording(self, recorded_chunks, session, stop_event, recording_start):
        speech_detected = False; silence_start_time = None; speech_start_time = None
        while True:
            time.sleep(0.05)
            if not session or (stop_event and stop_event.is_set()): break
            if not self._is_candidate_present(session): break
            elapsed = (datetime.now() - recording_start).total_seconds()
            if elapsed >= AudioConfig.MAX_RECORDING_DURATION_SEC: break
            if len(recorded_chunks) > 5:
                volume = np.sqrt(np.mean(np.concatenate(recorded_chunks[-5:], axis=0)**2))
                if volume > AudioConfig.VOLUME_THRESHOLD:
                    silence_start_time = None
                    if not speech_detected:
                        if speech_start_time is None: speech_start_time = time.time()
                        if (time.time() - speech_start_time) >= AudioConfig.MIN_SPEECH_DURATION_SEC: speech_detected = True
                elif speech_detected:
                    if silence_start_time is None: silence_start_time = time.time()
                    if elapsed >= AudioConfig.MIN_RECORDING_SEC and (time.time() - silence_start_time) > AudioConfig.SILENCE_THRESHOLD_SEC: break
                else: speech_start_time = None

    def _is_candidate_present(self, session: dict) -> bool:
        try:
            controller = session.get('controller')
            lock = session.get('lock')
            if not controller:
                return True
            if lock:
                with lock:
                    return controller.get_participant_count() >= 2
            return controller.get_participant_count() >= 2
        except Exception:
            return True

    def _save_recorded_audio(self, recorded_chunks: list, session_id: str, turn_count: int, is_follow_up: bool):
        try:
            if not recorded_chunks: return
            recording_data = np.concatenate(recorded_chunks, axis=0)
            audio_path = get_user_audio_path_for_stt(session_id, turn_count, is_follow_up)
            save_audio_file(recording_data, audio_path, self.samplerate)
        except Exception as e:
            logger.error(f"Error saving audio: {e}")
