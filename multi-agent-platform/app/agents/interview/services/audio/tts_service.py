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
import json
import hashlib

from app.agents.interview.config.constants import AudioConfig, ServiceConfig

logger = logging.getLogger(__name__)


# The replacement text is sent only to the TTS provider; it never changes the
# transcript, LLM prompt, interview report, or webhook payload.
DEFAULT_PRONUNCIATION_GLOSSARY = {
    # Stack names should sound like words.
    "MERN": "mern",
    "MEAN": "mean",
    "PERN": "pern",
    "LAMP": "lamp",
    "JAMstack": "jam stack",
    # These are normally intended to be pronounced letter by letter.
    "API": "A P I",
    "AWS": "A W S",
    "SQL": "S Q L",
    "HTML": "H T M L",
    "CSS": "C S S",
    "CI/CD": "C I slash C D",
}


class TTSService:
    def __init__(self):
        self._session_tts_char_counts = defaultdict(int)
        self._logging_tasks = defaultdict(list)
        self._logging_tasks_lock = threading.Lock()
        self._usage_lock = threading.Lock()
        self.cache_dir = Path("data/static_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tts_model = ServiceConfig.GEMINI_TTS_MODEL
        self.tts_voice_name = ServiceConfig.TTS_VOICE_NAME
        self.tts_language = ServiceConfig.TTS_VOICE_LANGUAGE
        self._pronunciation_glossary = self._load_pronunciation_glossary()
        self._pronunciation_pattern = self._compile_pronunciation_pattern()
        glossary_fingerprint = hashlib.sha256(
            json.dumps(self._pronunciation_glossary, sort_keys=True).encode("utf-8")
        ).hexdigest()[:8]
        self.cache_namespace = re.sub(
            r"[^a-zA-Z0-9_-]",
            "_",
            f"{self.tts_model}_{self.tts_voice_name}_{glossary_fingerprint}",
        )
        try:
            self.tts_client = texttospeech.TextToSpeechClient(client_options=ClientOptions(api_endpoint="texttospeech.googleapis.com:443"))
            self.tts_voice = texttospeech.VoiceSelectionParams(
                language_code=self.tts_language,
                name=self.tts_voice_name,
                model_name=self.tts_model,
            )
            self.audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=AudioConfig.SAMPLE_RATE_24K,
            )
            self.streaming_config = texttospeech.StreamingSynthesizeConfig(
                voice=self.tts_voice,
                streaming_audio_config=texttospeech.StreamingAudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MULAW,
                    sample_rate_hertz=AudioConfig.SAMPLE_RATE_24K,
                ),
            )
            logger.info("TTS configured with model=%s voice=%s locale=%s", self.tts_model, self.tts_voice_name, self.tts_language)
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
        return self._apply_pronunciation_glossary(text)

    def _load_pronunciation_glossary(self) -> Dict[str, str]:
        """Load safe defaults, optionally extended by environment JSON."""
        glossary = {
            term.casefold(): pronunciation
            for term, pronunciation in DEFAULT_PRONUNCIATION_GLOSSARY.items()
        }
        raw_overrides = ServiceConfig.TTS_PRONUNCIATION_OVERRIDES_JSON.strip()
        if not raw_overrides:
            return glossary
        try:
            overrides = json.loads(raw_overrides)
        except json.JSONDecodeError as error:
            logger.warning("Ignoring invalid TTS_PRONUNCIATION_OVERRIDES_JSON: %s", error)
            return glossary
        if not isinstance(overrides, dict):
            logger.warning("Ignoring TTS_PRONUNCIATION_OVERRIDES_JSON because it must be a JSON object")
            return glossary

        for term, pronunciation in overrides.items():
            if not isinstance(term, str) or not term.strip() or not isinstance(pronunciation, str) or not pronunciation.strip():
                logger.warning("Ignoring invalid TTS pronunciation override entry")
                continue
            glossary[term.strip().casefold()] = pronunciation.strip()
        return glossary

    def _compile_pronunciation_pattern(self) -> Optional[re.Pattern]:
        if not self._pronunciation_glossary:
            return None
        terms = sorted(self._pronunciation_glossary, key=len, reverse=True)
        return re.compile(
            r"(?<![A-Za-z0-9])(" + "|".join(re.escape(term) for term in terms) + r")(?![A-Za-z0-9])",
            flags=re.IGNORECASE,
        )

    def _apply_pronunciation_glossary(self, text: str) -> str:
        if not self._pronunciation_pattern:
            return text
        return self._pronunciation_pattern.sub(
            lambda match: self._pronunciation_glossary[match.group(0).casefold()],
            text,
        )

    def _get_safe_cache_path(self, filename_key: str) -> Optional[Path]:
        safe_name = Path(filename_key or "").name.strip()
        if not safe_name:
            return None
        if not safe_name.endswith(".wav"):
            safe_name += ".wav"
        # A model/voice-specific namespace prevents old Chirp cache entries
        # from being played after a Gemini-TTS model migration.
        return self.cache_dir / f"{self.cache_namespace}_{safe_name}"

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
            response = None
            for attempt in range(1, 4):
                try:
                    response = self.tts_client.synthesize_speech(
                        request={
                            "input": texttospeech.SynthesisInput(text=processed_text),
                            "voice": self.tts_voice,
                            "audio_config": self.audio_config,
                        }
                    )
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    logger.warning("Gemini-TTS static synthesis failed (attempt %s/3); retrying", attempt)
                    time.sleep(0.5 * attempt)
            if not getattr(response, "audio_content", None):
                logger.error("Gemini-TTS returned no audio for static cache key %s", filename_key)
                return None
            with open(file_path, "wb") as out: out.write(response.audio_content)
            return file_path
        except Exception as e:
            logger.error(f"Failed to generate Gemini-TTS static audio: {e}", exc_info=True)
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
            yield texttospeech.StreamingSynthesizeRequest(streaming_config=self.streaming_config)
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
        except Exception as error:
            logger.error("Gemini-TTS streaming synthesis failed: %s", error, exc_info=True)

    def stream_plain_text(self, plain_text: str, session_id: str, turn_count: Any, is_follow_up: bool = False) -> iter:
        if not self.tts_client: return
        if not plain_text or not plain_text.strip(): return
        try:
            self._enqueue_usage_log(plain_text, session_id, turn_count, is_follow_up)
            def request_generator():
                yield texttospeech.StreamingSynthesizeRequest(streaming_config=self.streaming_config)
                yield texttospeech.StreamingSynthesizeRequest(input={'text': self._preprocess_for_tts(plain_text)})
            for res in self.tts_client.streaming_synthesize(requests=request_generator()):
                if res.audio_content: yield res.audio_content
        except Exception as error:
            logger.error("Gemini-TTS plain-text streaming failed: %s", error, exc_info=True)

    def _enqueue_usage_log(self, text, session_id, turn_count, is_follow_up):
        def worker():
            with self._usage_lock: self._session_tts_char_counts[session_id] += len(text)
        threading.Thread(target=worker, daemon=True).start()

    def end_session(self, session_id: str):
        if session_id in self._session_tts_char_counts: del self._session_tts_char_counts[session_id]
