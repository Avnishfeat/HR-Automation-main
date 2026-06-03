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

    def _preprocess_for_tts(self, text: str) -> str:
        if not text: return text
        # Fix common file extensions that TTS reads awkwardly
        text = re.sub(r'\b(Node|Vue|React|Next|Nuxt|Nest|Express)\.js\b', r'\1 js', text, flags=re.IGNORECASE)
        text = re.sub(r'\.js\b', ' js', text, flags=re.IGNORECASE)
        text = re.sub(r'\.ts\b', ' ts', text, flags=re.IGNORECASE)
        text = re.sub(r'\.py\b', ' py', text, flags=re.IGNORECASE)
        return text

    def _get_safe_cache_path(self, filename_key: str) -> Optional[Path]:
        safe_name = Path(filename_key or "").name.strip()
        if not safe_name:
            return None
        if not safe_name.endswith(".wav"):
            safe_name += ".wav"
        return self.cache_dir / safe_name

    def get_or_create_static_audio(self, text: str, filename_key: str) -> Optional[Path]:
        if not text or not text.strip():
            return None
        file_path = self._get_safe_cache_path(filename_key)
        if not file_path:
            return None
        if file_path.exists(): return file_path
        if not self.tts_client: return None
        try:
            processed_text = self._preprocess_for_tts(text)
            response = self.tts_client.synthesize_speech(request={"input": texttospeech.SynthesisInput(text=processed_text), "voice": self.tts_voice, "audio_config": self.audio_config})
            if not getattr(response, "audio_content", None):
                return None
            with open(file_path, "wb") as out: out.write(response.audio_content)
            return file_path
        except Exception as e:
            logger.error(f"Failed to generate static audio: {e}")
            return None

    def stream_tts_from_text_generator(self, text_generator: iter, session_id: str, turn_count: Any, is_follow_up: bool) -> iter:
        if not self.tts_client: return
        full_text = []
        text_iterator = iter(text_generator)
        try:
            first = next((text for text in text_iterator if text and text.strip()), None)
            if not first: return
            full_text.append(first)
        except StopIteration: return
        def request_generator():
            yield texttospeech.StreamingSynthesizeRequest(streaming_config={'voice': {'language_code': 'en-IN', 'name': 'en-IN-Chirp3-HD-Alnilam'}, 'streaming_audio_config': self.streaming_audio_config})
            yield texttospeech.StreamingSynthesizeRequest(input={'text': self._preprocess_for_tts(first)})
            for s in text_iterator:
                if not s or not s.strip():
                    continue
                full_text.append(s)
                yield texttospeech.StreamingSynthesizeRequest(input={'text': self._preprocess_for_tts(s)})
        try:
            for res in self.tts_client.streaming_synthesize(requests=request_generator()):
                if res.audio_content: yield res.audio_content
            if full_text: self._enqueue_usage_log(" ".join(full_text), session_id, turn_count, is_follow_up)
        except Exception: pass

    def stream_plain_text(self, plain_text: str, session_id: str, turn_count: Any, is_follow_up: bool = False) -> iter:
        if not self.tts_client: return
        if not plain_text or not plain_text.strip(): return
        try:
            self._enqueue_usage_log(plain_text, session_id, turn_count, is_follow_up)
            def request_generator():
                yield texttospeech.StreamingSynthesizeRequest(streaming_config={'voice': {'language_code': 'en-IN', 'name': 'en-IN-Chirp3-HD-Alnilam'}, 'streaming_audio_config': self.streaming_audio_config})
                yield texttospeech.StreamingSynthesizeRequest(input={'text': self._preprocess_for_tts(plain_text)})
            for res in self.tts_client.streaming_synthesize(requests=request_generator()):
                if res.audio_content: yield res.audio_content
        except Exception: pass

    def _enqueue_usage_log(self, text, session_id, turn_count, is_follow_up):
        def worker():
            with self._usage_lock: self._session_tts_char_counts[session_id] += len(text)
        threading.Thread(target=worker, daemon=True).start()

    def end_session(self, session_id: str):
        if session_id in self._session_tts_char_counts: del self._session_tts_char_counts[session_id]
