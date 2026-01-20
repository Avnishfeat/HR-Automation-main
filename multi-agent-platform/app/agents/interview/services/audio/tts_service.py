# app/services/tts_service.py
import os
import logging
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path
from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions
import numpy as np
import soundfile as sf
import threading
from collections import defaultdict
import re
import io

from app.agents.interview.core.ports.session_repository import SessionRepository

logger = logging.getLogger(__name__)

class TTSService:
    """
    Handles Text-to-Speech (TTS) with MongoDB persistence and local caching.
    """
    
    def __init__(self, db_handler: SessionRepository):
        self.db = db_handler
        self._session_tts_char_counts = defaultdict(int)
        
        # Setup Cache Directory (Transient/Local for playback)
        self.cache_dir = Path("data/static_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize TTS client
        try:
            custom_endpoint = "texttospeech.googleapis.com:443"
            self.tts_client = texttospeech.TextToSpeechClient(client_options=ClientOptions(api_endpoint=custom_endpoint))
            logger.info(" Google Cloud TTS client loaded.")
            
            self.tts_voice = texttospeech.VoiceSelectionParams(
                language_code="en-IN", 
                name="en-IN-Chirp3-HD-Alnilam"
            )
            
            self.audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16, 
                sample_rate_hertz=24000
            )
            
            self.streaming_audio_config = { 
                'audio_encoding': texttospeech.AudioEncoding.MULAW,
                'sample_rate_hertz': 24000
            }
            
        except Exception as e:
            logger.error(f"Failed load TTS client: {e}")
            self.tts_client = None

    def check_health(self) -> bool:
        if not self.tts_client: return False
        try:
            self.tts_client.list_voices()
            return True
        except Exception: return False
        
    def get_or_create_static_audio(self, text: str, filename_key: str) -> Optional[Path]:
        """
        Retrieves audio path. 
        Strategy: DB -> Local Cache. If missing, Generate -> DB -> Local Cache.
        """
        if not filename_key.endswith(".wav"):
            filename_key += ".wav"
            
        file_path = self.cache_dir / filename_key
        
        # 1. Check Local Cache (Fastest)
        if file_path.exists():
            return file_path
            
        # 2. Check MongoDB (Persistence)
        logger.info(f"Checking MongoDB for audio: {filename_key}")
        db_audio = self.db.get_file(filename_key)
        
        if db_audio:
            logger.info(f"Found in DB, downloading to local cache: {file_path}")
            with open(file_path, "wb") as f:
                f.write(db_audio)
            return file_path

        # 3. Generate New (if not in DB or Local)
        if not self.tts_client:
            logger.error("TTS client not available.")
            return None

        try:
            logger.info(f"Generating NEW static audio: '{filename_key}'")
            input_text = texttospeech.SynthesisInput(text=text)
            response = self.tts_client.synthesize_speech(
                request={
                    "input": input_text,
                    "voice": self.tts_voice,
                    "audio_config": self.audio_config
                }
            )
            audio_content = response.audio_content

            # A. Save to MongoDB (Golden Source)
            self.db.save_file(filename=filename_key, data=audio_content)

            # B. Save to Local (For Playback)
            with open(file_path, "wb") as out:
                out.write(audio_content)
                
            return file_path
            
        except Exception as e:
            logger.error(f"Failed to generate static audio: {e}", exc_info=True)
            return None

    def stream_tts_from_text_generator(self, text_generator: iter, session_id: str, turn_count: Any, candidate_id: str, is_follow_up: bool) -> iter:
        if not self.tts_client: return

        full_question_text = []
        try:
            first_sentence = next(text_generator)
            if not first_sentence: return
            full_question_text.append(first_sentence)
        except StopIteration: return
        except Exception:
            yield from self.stream_plain_text("Apologies, an error occurred.", session_id, turn_count, candidate_id)
            return

        def request_generator():
            yield texttospeech.StreamingSynthesizeRequest(
                streaming_config={
                    'voice': {'language_code': 'en-IN', 'name': 'en-IN-Chirp3-HD-Alnilam'},
                    'streaming_audio_config': self.streaming_audio_config
                }
            )
            yield texttospeech.StreamingSynthesizeRequest(input={'text': first_sentence})
            for sentence in text_generator:
                full_question_text.append(sentence)
                yield texttospeech.StreamingSynthesizeRequest(input={'text': sentence})

        try:
            tts_stream = self.tts_client.streaming_synthesize(requests=request_generator())
            for tts_response in tts_stream:
                if tts_response.audio_content:
                    yield tts_response.audio_content

            combined_text = " ".join(full_question_text)
            if combined_text:
                self._log_usage_and_save(combined_text, session_id, turn_count, candidate_id, is_follow_up)

        except Exception as e:
            logger.error(f"Error in stream_tts: {e}", exc_info=True)
            yield from self.stream_plain_text("Apologies, an error occurred.", session_id, turn_count, candidate_id)

    def stream_plain_text(self, plain_text: str, session_id: str, turn_count: Any, candidate_id: str, is_follow_up: bool = False) -> iter:
        if not self.tts_client: return
        try:
            self._log_usage_and_save(plain_text, session_id, turn_count, candidate_id, is_follow_up)
            def request_generator():
                yield texttospeech.StreamingSynthesizeRequest(
                    streaming_config={
                        'voice': {'language_code': 'en-IN', 'name': 'en-IN-Chirp3-HD-Alnilam'},
                        'streaming_audio_config': self.streaming_audio_config
                    }
                )
                yield texttospeech.StreamingSynthesizeRequest(input={'text': plain_text})

            tts_stream = self.tts_client.streaming_synthesize(requests=request_generator())
            for tts_response in tts_stream:
                if tts_response.audio_content: yield tts_response.audio_content
        except Exception as e:
            logger.error(f"Plain text streaming TTS fail: {e}", exc_info=True)

    def _log_usage_and_save(self, text: str, session_id: str, turn_count: Any, candidate_id: str, is_follow_up: bool):
        char_count = len(text)
        self._session_tts_char_counts[session_id] += char_count
        self.db.update_tts_character_usage(session_id, char_count)
        self.db.add_message_to_session(
            session_id, "assistant", text, 
            audio_path="[Streamed]", 
            is_follow_up=is_follow_up, turn_count=turn_count
        )

    def end_session(self, session_id: str):
        if session_id in self._session_tts_char_counts:
            del self._session_tts_char_counts[session_id]