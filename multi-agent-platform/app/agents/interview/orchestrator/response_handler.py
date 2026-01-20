# app/orchestrator/response_handler.py
import logging
import asyncio
from typing import Callable, Awaitable

from .types import (
    InterviewSession, InterviewState, ResponseData, HandlerResult
)
from app.agents.interview.config.constants import StaticMessages, InterviewTiming

logger = logging.getLogger(__name__)

class InterviewResponseHandler:
    def __init__(self, interview_service, audio_handler, stt_service):
        self.interview_svc = interview_service
        self.audio_handler = audio_handler
        self.stt_service = stt_service

    async def handle_response(
        self,
        session: InterviewSession,
        state: InterviewState,
        response: ResponseData,
        record_next_callback: Callable[[InterviewSession, int, bool], Awaitable[ResponseData]] 
    ) -> HandlerResult:
        
        transcript = response.transcript.strip()
        
        # 1. Handle Empty/Silence immediately
        if not transcript or transcript == "[No response]":
            return await self._handle_no_response(session, state, response, record_next_callback)

        # 2. Classify Intent using Gemini (Semantic Understanding)
        intent = await self._classify_intent_with_gemini(transcript)
        logger.info(f" Detected Intent: {intent} | Text: '{transcript[:50]}...'")

        # 3. Route based on Intent
        if intent == "EXIT":
            return await self._handle_exit_flow(session, state, response, record_next_callback)
            
        elif intent == "REPEAT":
            return await self._handle_repeat(session, state, response, record_next_callback)
            
        elif intent == "CLARIFICATION":
            return await self._handle_clarification(session, state, response, record_next_callback)

        # 4. Default: Treat as a valid ANSWER (Happy Path)
        return HandlerResult(final_response=response, proceed=True)

    # =========================================================================
    # INTENT CLASSIFIER (Fixed for New GenAI SDK)
    # =========================================================================

    async def _classify_intent_with_gemini(self, text: str) -> str:
        """
        Uses Gemini to classify intent into strict categories.
        Returns: ANSWER, EXIT, REPEAT, CLARIFICATION
        """
        try:
            prompt = (
                f"Analyze this candidate response from an interview: '{text}'.\n"
                "Classify the intent into exactly one of these categories:\n"
                "- EXIT (The user explicitly wants to end/stop/quit the interview)\n"
                "- REPEAT (The user missed what was said and wants it repeated)\n"
                "- CLARIFICATION (The user doesn't understand the question)\n"
                "- ANSWER (The user is answering the question, negotiating, or asking about logistics)\n"
                "Return ONLY the category name. No other text."
            )
            
            # FIX: Handle New Google GenAI SDK Structure
            gemini_svc = self.interview_svc.gemini_service
            
            # 1. Get the Client (New SDK usually puts it in .client)
            client = getattr(gemini_svc, 'client', None)
            if not client:
                logger.warning("Gemini Client not found in service. Defaulting to ANSWER.")
                return "ANSWER"

            # 2. Get Model Name (or default to flash)
            model_id = getattr(gemini_svc, 'model_name', 'gemini-2.5-flash')

            # 3. Call the API using the new signature
            # client.models.generate_content(model=..., contents=...)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_id,
                contents=prompt
            )
            
            if not response or not response.text:
                return "ANSWER"

            intent = response.text.strip().upper()
            
            # Safety check to ensure we get a valid category
            valid_intents = ["EXIT", "REPEAT", "CLARIFICATION", "ANSWER"]
            for v in valid_intents:
                if v in intent: 
                    return v
            
            return "ANSWER"
            
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return "ANSWER" # Fail-safe: continue interview

    # =========================================================================
    # CONTROL FLOW HANDLERS (Unchanged)
    # =========================================================================

    async def _handle_exit_flow(self, session, state, original_response, record_callback) -> HandlerResult:
        logger.warning("Exit intent trigger. Asking for confirmation...")
        
        await self._play_audio(session, StaticMessages.EXIT_REDIRECT, StaticMessages.CACHE_KEY_WARNING_EXIT)
        
        confirmation_response = await record_callback(session, state.turn_count, True)
        confirm_text = confirmation_response.transcript.lower().strip()
        
        is_confirmed = any(word in confirm_text for word in ['yes', 'yeah', 'stop', 'end', 'quit', 'sure', 'terminate', 'confirm'])
        
        if is_confirmed:
             logger.info(f"User confirmed exit: '{confirm_text}'. Ending session.")
             return HandlerResult(final_response=confirmation_response, proceed=False)
        
        logger.info(f"User cancelled exit: '{confirm_text}'. Resuming interview.")
        
        # 1. Play Acknowledgement
        await self._play_audio(session, "Okay, let's continue.", "system_resume_ack")
        
        # FIX: Add a pause to let the audio finish and connections close
        await asyncio.sleep(1.5) 
        
        # 2. Replay the Question
        await self._replay_last_question(session, state)
        
        final_response = await record_callback(session, state.turn_count + 1, False)
        return HandlerResult(final_response=final_response, proceed=True)

    async def _handle_clarification(self, session, state, original, record_callback) -> HandlerResult:
        logger.info("Clarification request")
        await self._replay_last_question(session, state)
        new_response = await record_callback(session, state.turn_count + 1, False)
        return HandlerResult(final_response=new_response, proceed=True)

    async def _handle_repeat(self, session, state, original, record_callback) -> HandlerResult:
        logger.info("Repeat request")
        await self._replay_last_question(session, state)
        new_response = await record_callback(session, state.turn_count + 1, False)
        return HandlerResult(final_response=new_response, proceed=True)

    async def _handle_no_response(self, session, state, original, record_callback) -> HandlerResult:
        logger.warning("No response detected")
        await self._play_audio(session, StaticMessages.NO_RESPONSE, StaticMessages.CACHE_KEY_ERROR_NO_RESPONSE)
        await self._replay_last_question(session, state)
        new_response = await record_callback(session, state.turn_count + 1, False)
        return HandlerResult(final_response=new_response, proceed=True)

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _play_audio(self, session, text, cache_key):
        await asyncio.to_thread(session.meet.enable_microphone)
        await asyncio.sleep(InterviewTiming.MIC_TOGGLE_DELAY_SEC)
        
        path = self.interview_svc.get_static_audio_path(text, cache_key)
        if path:
            await asyncio.to_thread(self.audio_handler.play_wav_file, path, session.meet, session.stop_event)

    async def _replay_last_question(self, session, state):
        question_turn = max(1, state.turn_count - 1)
        stream = self.interview_svc.stream_interview_turn(
            session.session_id, 
            state.turn_count + 1, 
            session.candidate_id, 
            replay_from_turn=question_turn
        )
        if stream:
            await asyncio.to_thread(self.audio_handler.play_audio_stream, stream, session.meet, session.stop_event)