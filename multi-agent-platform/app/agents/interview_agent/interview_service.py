
# app/services/interview/interview_service.py
import logging
import asyncio
import re
import hashlib
from datetime import datetime
from typing import Optional, List, Iterator, Dict
from pathlib import Path

from app.core.ports.session_repository import SessionRepository
from app.agents.interview_agent.llm.gemini_service import GeminiService
from app.agents.interview_agent.audio.tts_service import TTSService
from app.agents.interview_agent.transcript_manager import TranscriptManager
from app.agents.interview_agent.analysis.combined_analyzer import CombinedAnalyzer

logger = logging.getLogger(__name__)

class InterviewService:
    def __init__(self, db_handler: SessionRepository, combined_analyzer: CombinedAnalyzer):
        self.db = db_handler
        self.gemini_service = GeminiService(self.db)
        self.tts_service = TTSService(self.db)
        self.transcript_manager = TranscriptManager(self.db)
        self.combined_analyzer = combined_analyzer
        self.candidate_names: Dict[str, str] = {}

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    async def start_new_interview(
        self,
        resume_text: str,
        candidate_id: str,
        job_role: str,
        questionnaire: List[str],
        job_description: Optional[str] = None
    ) -> str:
        
        # Async implementation to avoid blocking event loop
        try:
             session_id = await self.db.create_new_session(
                resume_text,
                candidate_id,
                job_role,
                questionnaire or [],
                job_description
             )
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise e
            
        logger.info(f"Starting interview session: {session_id} for role: {job_role}")
        
        candidate_name = self._extract_candidate_name(resume_text)
        self.candidate_names[session_id] = candidate_name
        logger.info(f"Extracted candidate name: {candidate_name}")
        
        try:
            self.gemini_service.start_chat_session(
                session_id,
                resume_text,
                questionnaire,
                job_role,
                job_description
            )
            
            self.transcript_manager.initialize_transcript_state(session_id)
            
        except Exception as e:
            if session_id in self.candidate_names:
                del self.candidate_names[session_id]
            logger.error(f"Failed to start interview services: {e}", exc_info=True)
            raise
        
        return session_id

    def end_interview_session(self, session_id: str):
        if session_id in self.candidate_names:
            del self.candidate_names[session_id]
        
        self.gemini_service.end_session(session_id)
        self.tts_service.end_session(session_id)
        self.transcript_manager.clear_session_state(session_id)
        
        # Save final transcript to MongoDB instead of disk
        self.transcript_manager.save_final_transcript_to_db(session_id)
        
        logger.info(f"Interview services stopped and data persisted for {session_id}")

    # =========================================================================
    # ANALYSIS & REPORTING
    # =========================================================================
    
    # This method is kept if you want to trigger it manually via API, 
    # but it is no longer called automatically by end_interview_session
    async def trigger_post_interview_analysis(self, session_id: str):
        """
        Triggers the full Combined Analysis (Transcript + Voice + Behavioral).
        """
        logger.info(f"Triggering FINAL COMBINED ANALYSIS for {session_id}...")

        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # session_data = self.db.get_full_session(session_id)
            if loop.is_running():
                 # Calling async db from async method - await directly
                 session_data = await self.db.get_full_session(session_id)
            else:
                 session_data = loop.run_until_complete(self.db.get_full_session(session_id))

            if not session_data:
                logger.error(f"Session {session_id} not found.")
                return

            candidate_id = session_data.get("candidate_id", "unknown")

            # Run Combined Analysis (Synchronously in a thread)
            report = await asyncio.to_thread(
                self.combined_analyzer.combine_analyses,
                behavioral_result=None, 
                transcript_result=None, 
                voice_result=None,      
                session_id=session_id,
                candidate_id=candidate_id
            )

            if report:
                logger.info(f"Combined Analysis Complete. Score: {report.final_weighted_score}")
            else:
                logger.error("Combined Analysis returned None.")

        except Exception as e:
            logger.error(f"Analysis Trigger Failed: {e}", exc_info=True)
            # self.db.mark_analysis_pending(session_id)
            try:
                await self.db.mark_analysis_pending(session_id)
            except: pass

    # =========================================================================
    # GREETING GENERATION
    # =========================================================================

    def generate_initial_greeting(self, session_id: str) -> str:
        """
        Generates personalized opening greeting for HR screening.
        """
        name = self.candidate_names.get(session_id, "Candidate")
        
        base = (
            "Hello and welcome. I am Eva, your HR recruiter for today's screening. "
            "For our conversation today, please ensure your camera is turned on "
            "and remains on throughout the interview. "
            "Also, please make sure your microphone is enabled when you are speaking. "
        )
        
        if name == "Candidate":
            dynamic = (
                "To start, could you please introduce yourself and tell me about your background."
            )
        else:
            dynamic = (
                f"Hello {name}. Let's begin. Please tell me about your background "
                f"and what brings you here today."
            )
        
        return base + dynamic

    # =========================================================================
    # AUDIO GENERATION
    # =========================================================================

    async def get_static_audio_path(self, text: str, key_suffix: str) -> Optional[Path]:
        """Gets or creates cached audio for static messages."""
        safe_key = re.sub(r'[^a-zA-Z0-9]', '_', key_suffix).lower()
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()[:8]
        full_key = f"{safe_key}_{text_hash}"
        
        return await self.tts_service.get_or_create_static_audio(text, full_key)

    def stream_interview_turn(
        self,
        session_id: str,
        turn_count: int,
        candidate_id: str,
        replay_from_turn: Optional[int] = None
    ) -> Optional[Iterator[bytes]]:
        """
        Generates and streams a complete HR screening interview turn (question).
        """
        if replay_from_turn is not None:
            return self._replay_question(
                session_id, turn_count, candidate_id, replay_from_turn
            )
        
        try:
            last_answer = self.transcript_manager.get_latest_transcript(session_id)
            sentence_generator = self.gemini_service.stream_gemini_sentences(
                session_id, last_answer
            )
        except Exception as e:
            logger.error(f"Error creating Gemini generator: {e}", exc_info=True)
            return self.stream_plain_text(
                "Apologies, an error occurred.",
                session_id,
                turn_count,
                candidate_id
            )
        
        try:
            return self.tts_service.stream_tts_from_text_generator(
                sentence_generator,
                session_id,
                turn_count,
                candidate_id,
                is_follow_up=False
            )
        except Exception as e:
            logger.error(f"Error in TTS streaming: {e}", exc_info=True)
            return self.stream_plain_text(
                "Apologies, an error occurred.",
                session_id,
                turn_count,
                candidate_id
            )

    def stream_plain_text(
        self,
        plain_text: str,
        session_id: str,
        turn_count: int,
        candidate_id: str,
        is_follow_up: bool = False
    ) -> Optional[Iterator[bytes]]:
        """Streams plain text directly to TTS."""
        try:
            return self.tts_service.stream_plain_text(
                plain_text,
                session_id,
                turn_count,
                candidate_id,
                is_follow_up
            )
        except Exception as e:
            logger.error(f"Error streaming plain text: {e}", exc_info=True)
            return None

    # =========================================================================
    # TRANSCRIPT MANAGEMENT
    # =========================================================================

    def process_and_log_transcript(
        self,
        session_id: str,
        audio_path: str,
        transcript: str,
        turn_count: int,
        candidate_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        is_follow_up_response: bool = False
    ):
        """Delegates transcript processing and logging to TranscriptManager."""
        self.transcript_manager.process_and_log_transcript(
            session_id,
            audio_path,
            transcript,
            turn_count,
            candidate_id,
            start_time,
            end_time,
            is_follow_up_response
        )

    def generate_final_transcript_file(self, session_id: str):
        """Generates the final transcript file."""
        try:
            self.transcript_manager.generate_final_transcript_file(session_id)
        except Exception as e:
            logger.error(f"Failed to generate transcript: {e}", exc_info=True)

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _extract_candidate_name(self, resume_text: str) -> str:
        try:
            extracted = self.gemini_service.extract_candidate_name(resume_text)
            return extracted if extracted else "Candidate"
        except Exception as e:
            logger.warning(f"Name extraction failed: {e}. Using 'Candidate'")
            return "Candidate"

    def _replay_question(
        self,
        session_id: str,
        turn_count: int,
        candidate_id: str,
        replay_from_turn: int
    ) -> Optional[Iterator[bytes]]:
        """Replays a previous question as a new turn."""
        logger.info(
            f"Replaying question from turn {replay_from_turn} as turn {turn_count}"
        )
        
        try:
            # Sync wrapper for get_full_session
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self.db.get_full_session(session_id), loop)
                session_data = future.result()
            else:
                 session_data = loop.run_until_complete(self.db.get_full_session(session_id))
            
            if not session_data or 'conversation' not in session_data:
                logger.error(f"Session {session_id} not found or has no conversation")
                return self._stream_fallback_question(session_id, turn_count, candidate_id)
            
            message_to_replay = None
            for msg in session_data['conversation']:
                if (msg.get('turn') == replay_from_turn and 
                    msg.get('role') == 'assistant'):
                    message_to_replay = msg.get('text')
                    break
            
            if not message_to_replay:
                logger.warning(f"Could not find turn {replay_from_turn} to replay")
                return self._stream_fallback_question(session_id, turn_count, candidate_id)
            
            question_only = self._extract_question_from_text(message_to_replay)
            replay_text = question_only or message_to_replay
            
            return self.tts_service.stream_plain_text(
                replay_text,
                session_id,
                turn_count,
                candidate_id,
                is_follow_up=False
            )
            
        except Exception as e:
            logger.error(f"Error during question replay: {e}", exc_info=True)
            return self._stream_fallback_question(session_id, turn_count, candidate_id)

    def _extract_question_from_text(self, text: str) -> str:
        if not text:
            return ""
        
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        
        question_sentence = None
        for sentence in reversed(sentences):
            stripped = sentence.strip()
            if not stripped:
                continue
            question_sentence = stripped
            if stripped.endswith('?'):
                break
        
        return question_sentence or text.strip()

    def _stream_fallback_question(
        self,
        session_id: str,
        turn_count: int,
        candidate_id: str
    ) -> Iterator[bytes]:
        fallback = (
            "My apologies, I lost my train of thought. "
            "Let me ask you this instead. "
            "What motivated you to apply for this position?"
        )
        result = self.tts_service.stream_plain_text(
            fallback,
            session_id,
            turn_count,
            candidate_id,
            is_follow_up=False
        )
        return result if result is not None else iter([])
