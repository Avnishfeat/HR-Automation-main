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
        state.last_user_transcript = transcript or None
        
        # 1. Handle empty/silence immediately
        if not transcript or transcript == "[No response]":
            return await self._handle_no_response(session, state, response, record_next_callback)

        # 2. Prevent candidate from ending the interview early.
        # If they try to exit, politely deny and redirect.
        if self._looks_like_exit_request(transcript):
            logger.info("Exit request detected; denying exit and redirecting.")
            await self._play_audio(
                session,
                StaticMessages.EXIT_REDIRECT,
                "exit_redirect",
                state.turn_count
            )
            await self._replay_last_question(session, state)
            await asyncio.sleep(1.5)
            await session.meet.disable_microphone()
            new_response = await record_next_callback(session, state.turn_count + 1, False)
            return HandlerResult(final_response=new_response, proceed=True)

        # 3. Default: treat as a normal answer or control request that the
        # main interview prompt can respond to directly.
        return HandlerResult(final_response=response, proceed=True)

    # =========================================================================
    # CONTROL FLOW HANDLERS
    # =========================================================================

    async def _handle_no_response(self, session, state, original, record_callback) -> HandlerResult:
        logger.warning("No response detected")
        await self._play_audio(session, StaticMessages.NO_RESPONSE, StaticMessages.CACHE_KEY_ERROR_NO_RESPONSE, state.turn_count)
        await self._replay_last_question(session, state)
        # FIX: Wait for virtual cable to drain before disabling the mic
        # so the retry response isn't cut off.
        await asyncio.sleep(1.5)
        await session.meet.disable_microphone()
        new_response = await record_callback(session, state.turn_count + 1, False)
        return HandlerResult(final_response=new_response, proceed=True)

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _play_audio(self, session, text, cache_key, turn_count):
        await session.meet.enable_microphone()
        await asyncio.sleep(InterviewTiming.MIC_TOGGLE_DELAY_SEC)
        self.interview_svc.log_assistant_message(session.session_id, text, turn_count)

        path = self.interview_svc.get_static_audio_path(text, cache_key)
        if path:
            await asyncio.to_thread(self.audio_handler.play_wav_file, path, session.meet, session.stop_event)

    async def _replay_last_question(self, session, state):
        question_turn = max(1, state.turn_count - 1)
        stream = self.interview_svc.stream_interview_turn(
            session.session_id,
            state.turn_count + 1,
            replay_from_turn=question_turn
        )
        if stream:
            await asyncio.to_thread(self.audio_handler.play_audio_stream, stream, session.meet, session.stop_event)

    @staticmethod
    def _looks_like_exit_request(transcript: str) -> bool:
        text = transcript.lower()
        exit_phrases = (
            "end the interview",
            "stop the interview",
            "quit the interview",
            "leave the interview",
            "end this interview",
            "stop this interview",
            "quit this interview",
            "i want to end",
            "i want to stop",
            "i want to quit",
            "can we stop",
            "can we end",
            "please stop",
            "please end",
            "terminate the interview",
        )
        return any(phrase in text for phrase in exit_phrases)
