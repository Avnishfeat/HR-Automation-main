# app/services/tts_service.py
import os
import logging
import time
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path
from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions
import numpy as np
import threading
from collections import defaultdict
import re
import io

logger = logging.getLogger(__name__)

class TTSService:
    def __init__(self):
        self._session_tts_char_counts = defaultdict(int)
        self._logging_tasks = defaultdict(list)
        self._logging_tasks_lock = threading.Lock()
        self._usage_lock = threading.Lock()
        self.cache_dir = Path("data/static_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.tts_client = texttospeech.TextToSpeechClient(client_options=ClientOptions(api_endpoint="texttospeech.googleapis.com:443"))
            self.tts_voice = texttospeech.VoiceSelectionParams(language_code="en-IN", name="en-IN-Chirp3-HD-Alnilam")
            self.audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.LINEAR16, sample_rate_hertz=24000)
            self.streaming_audio_config = {'audio_encoding': texttospeech.AudioEncoding.MULAW, 'sample_rate_hertz': 24000}
        except Exception as e:
            logger.error(f"Failed to load TTS client: {e}")
            self.tts_client = None

    def get_or_create_static_audio(self, text: str, filename_key: str) -> Optional[Path]:
        if not filename_key.endswith(".wav"): filename_key += ".wav"
        file_path = self.cache_dir / filename_key
        if file_path.exists(): return file_path
        if not self.tts_client: return None
        try:
            response = self.tts_client.synthesize_speech(request={"input": texttospeech.SynthesisInput(text=text), "voice": self.tts_voice, "audio_config": self.audio_config})
            with open(file_path, "wb") as out: out.write(response.audio_content)
            return file_path
        except Exception as e:
            logger.error(f"Failed to generate static audio: {e}")
            return None

    def stream_tts_from_text_generator(self, text_generator: iter, session_id: str, turn_count: Any, is_follow_up: bool) -> iter:
        if not self.tts_client: return
        full_text = []
        try:
            first = next(text_generator)
            if not first: return
            full_text.append(first)
        except StopIteration: return
        def request_generator():
            yield texttospeech.StreamingSynthesizeRequest(streaming_config={'voice': {'language_code': 'en-IN', 'name': 'en-IN-Chirp3-HD-Alnilam'}, 'streaming_audio_config': self.streaming_audio_config})
            yield texttospeech.StreamingSynthesizeRequest(input={'text': first})
            for s in text_generator:
                full_text.append(s)
                yield texttospeech.StreamingSynthesizeRequest(input={'text': s})
        try:
            for res in self.tts_client.streaming_synthesize(requests=request_generator()):
                if res.audio_content: yield res.audio_content
            if full_text: self._enqueue_usage_log(" ".join(full_text), session_id, turn_count, is_follow_up)
        except Exception: pass

    def stream_plain_text(self, plain_text: str, session_id: str, turn_count: Any, is_follow_up: bool = False) -> iter:
        if not self.tts_client: return
        try:
            self._enqueue_usage_log(plain_text, session_id, turn_count, is_follow_up)
            def request_generator():
                yield texttospeech.StreamingSynthesizeRequest(streaming_config={'voice': {'language_code': 'en-IN', 'name': 'en-IN-Chirp3-HD-Alnilam'}, 'streaming_audio_config': self.streaming_audio_config})
                yield texttospeech.StreamingSynthesizeRequest(input={'text': plain_text})
            for res in self.tts_client.streaming_synthesize(requests=request_generator()):
                if res.audio_content: yield res.audio_content
        except Exception: pass

    def _enqueue_usage_log(self, text, session_id, turn_count, is_follow_up):
        def worker():
            with self._usage_lock: self._session_tts_char_counts[session_id] += len(text)
        threading.Thread(target=worker, daemon=True).start()

    def end_session(self, session_id: str):
        if session_id in self._session_tts_char_counts: del self._session_tts_char_counts[session_id]
