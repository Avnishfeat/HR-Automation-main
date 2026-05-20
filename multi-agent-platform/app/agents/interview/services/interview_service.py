# app/services/interview_service.py
import logging
import asyncio
import re
import hashlib
import threading
import time
from datetime import datetime
from typing import Optional, List, Iterator, Dict
from pathlib import Path

from app.agents.interview.services.gemini_service import GeminiService
from app.agents.interview.services.audio.tts_service import TTSService
from app.agents.interview.services.transcript_manager import TranscriptManager
from app.agents.interview.services.analysis.combined_analyzer import CombinedAnalyzer

logger = logging.getLogger(__name__)

class InterviewService:
    def __init__(self, combined_analyzer: CombinedAnalyzer):
        self.gemini_service = GeminiService()
        self.tts_service = TTSService()
        self.transcript_manager = TranscriptManager()
        self.combined_analyzer = combined_analyzer
        self.candidate_names: Dict[str, str] = {}
        self._transcript_tasks: Dict[str, List[threading.Thread]] = {}
        self._transcript_tasks_lock = threading.Lock()

    def start_new_interview(self, resume_text, job_role, questionnaire, job_description=None, session_id=None) -> str:
        import uuid
        session_id = session_id or str(uuid.uuid4())
        try:
            name = self.gemini_service.extract_candidate_name(resume_text)
            self.candidate_names[session_id] = name
            self.gemini_service.start_chat_session(session_id, resume_text, questionnaire, job_role, job_description)
            self.transcript_manager.initialize_transcript_state(session_id)
            return session_id
        except Exception:
            self.candidate_names.pop(session_id, None)
            self.gemini_service.end_session(session_id)
            self.transcript_manager.clear_session_state(session_id)
            raise

    def get_candidate_name(self, session_id: str) -> str:
        return self.candidate_names.get(session_id, "Candidate")

    def finalize_interview_session(self, session_id: str) -> str:
        return self.transcript_manager.save_final_transcript(session_id)

    def cleanup_session_state(self, session_id: str):
        self.candidate_names.pop(session_id, None)
        self.gemini_service.end_session(session_id)
        self.tts_service.end_session(session_id)
        self.transcript_manager.clear_session_state(session_id)

    def end_interview_session(self, session_id: str):
        self.finalize_interview_session(session_id)
        self.cleanup_session_state(session_id)

    def generate_initial_greeting(self, session_id: str) -> str:
        name = self.candidate_names.get(session_id, "Candidate")
        return f"Hello {name}. I am Eva. Please introduce yourself."

    def get_static_audio_path(self, text, key):
        safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', str(key)).lower()
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
        return self.tts_service.get_or_create_static_audio(text, f"{safe_key}_{text_hash}")

    def stream_interview_turn(self, session_id, turn_count, replay_from_turn=None):
        if replay_from_turn is not None: return self._replay_question(session_id, turn_count, replay_from_turn)
        ans = self.transcript_manager.get_latest_transcript(session_id)
        gen = self._logging_sentence_generator(
            self.gemini_service.stream_gemini_sentences(session_id, ans),
            session_id,
            turn_count
        )
        return self.tts_service.stream_tts_from_text_generator(gen, session_id, turn_count, False)

    def stream_plain_text(self, text, session_id, turn_count, is_follow_up=False):
        self.log_assistant_message(session_id, text, turn_count)
        return self.tts_service.stream_plain_text(text, session_id, turn_count, is_follow_up)

    def process_and_log_transcript(self, session_id, audio_path, transcript, turn_count, start_time, end_time, is_follow_up=False):
        self.transcript_manager.process_and_log_transcript(session_id, audio_path, transcript, turn_count, start_time, end_time, is_follow_up)

    def log_assistant_message(self, session_id: str, text: str, turn_count: int):
        if text and text.strip():
            self.transcript_manager.log_assistant_message(session_id, text.strip(), turn_count)

    def _logging_sentence_generator(self, sentence_generator, session_id: str, turn_count: int):
        parts = []
        try:
            for sentence in sentence_generator:
                if sentence:
                    parts.append(sentence)
                    logger.info(f"[Bot Stream Chunk] {sentence.strip()}")
                yield sentence
        finally:
            assistant_text = " ".join(part.strip() for part in parts if part and part.strip()).strip()
            if assistant_text:
                logger.info(f"[Bot Stream Full] {assistant_text}")
                self.log_assistant_message(session_id, assistant_text, turn_count)

    def _replay_question(self, session_id, turn_count, replay_from_turn):
        history = self.transcript_manager.get_history(session_id)
        for msg in history:
            if msg.get('turn') == replay_from_turn and msg.get('role') == 'assistant':
                text = msg.get('text')
                self.log_assistant_message(session_id, text, turn_count)
                return self.tts_service.stream_plain_text(text, session_id, turn_count, False)
        return self._stream_fallback_question(session_id, turn_count)

    def _stream_fallback_question(self, session_id, turn_count):
        text = "What motivated you to apply?"
        self.log_assistant_message(session_id, text, turn_count)
        return self.tts_service.stream_plain_text(text, session_id, turn_count, False)
