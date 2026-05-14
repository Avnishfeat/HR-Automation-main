# app/services/gemini_service.py
import os
import re
import json
import logging
import threading
from typing import Dict, Any, List, Optional, Iterator
from collections import defaultdict
from google import genai
from google.genai import types
from app.agents.interview.core.retry_handler import retry_on_failure
from app.core.exceptions import (ExternalServiceError, ServiceInitializationError, InterviewBotException)
from app.agents.interview.config.prompt_templates import PromptTemplates 

logger = logging.getLogger(__name__)

class GeminiService:
    MODEL_NAME = "gemini-2.5-flash" 
    def __init__(self):
        self.active_chat_sessions: Dict[str, Any] = {}
        self._session_token_counts = defaultdict(lambda: {'prompt': 0, 'response': 0, 'total': 0})
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        try:
            from app.agents.interview.config.secrets import secrets
            self.client = genai.Client(api_key=secrets.get_required("GEMINI_API_KEY"))
            logger.info(" GeminiService: Client configured.")
        except Exception as e:
            logger.error(f"GeminiService Initialization Failed: {e}")

    def _get_config(self, temperature: float = 0.0) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(temperature=temperature, top_k=40, safety_settings=[types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH), types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH), types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH), types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)])

    def extract_candidate_name(self, resume_text: str) -> str:
        if not self.client: return "Candidate"
        try:
            p = f"Identify candidate Full Name from: {resume_text[:2000]}\nReturn ONLY the name."
            res = self.client.models.generate_content(model=self.MODEL_NAME, contents=p, config=self._get_config(0.0))
            name = (res.text or "Candidate").strip()
            return name if " " in name and len(name) < 50 else "Candidate"
        except Exception: return "Candidate"

    def start_chat_session(self, session_id: str, resume_text: str, questionnaire: List[str], job_role: str, job_description: Optional[str] = None):
        if not self.client: raise ServiceInitializationError("Gemini", "Client not initialized")
        system_prompt = self._build_system_prompt(resume_text, questionnaire, job_role, job_description)
        self._session_token_counts[session_id] = {'prompt': 0, 'response': 0, 'total': 0}
        history = [{"role": "user", "parts": [{"text": system_prompt}]}, {"role": "model", "parts": [{"text": "Understood."}]}]
        self.active_chat_sessions[session_id] = self.client.chats.create(model=self.MODEL_NAME, history=history, config=self._get_config(0.7))

    def stream_gemini_sentences(self, session_id: str, last_user_answer: str) -> Iterator[str]:
        chat = self.active_chat_sessions.get(session_id)
        if not chat: yield "Error: Session lost."; return
        try:
            buf = ""
            for chunk in chat.send_message_stream(message=last_user_answer):
                if not chunk.text: continue
                buf += chunk.text
                while True:
                    m = re.search(r'([^.!?]+[.!?])(\s+|$)', buf)
                    if m:
                        s = m.group(1).strip()
                        if s: yield s
                        buf = buf[len(m.group(0)):].lstrip()
                    else: break
            if buf.strip(): yield buf.strip()
        except Exception: yield "I didn't catch that."

    def end_session(self, session_id: str):
        self.active_chat_sessions.pop(session_id, None)
        self._session_token_counts.pop(session_id, None)

    def _build_system_prompt(self, resume_text, questionnaire, job_role, job_description):
        return (
            f"You are Eva, an AI HR Recruiter conducting an interview for the {job_role} role. "
            f"Resume: {resume_text[:2000]}. Questionnaire: {questionnaire}. JD: {job_description}. "
            f"The candidate has just been asked to introduce themselves. "
            f"Acknowledge their response naturally, then ask the first question from the questionnaire. "
            f"Respond in raw text, short sentences, conversational tone. Do NOT state that you are evaluating their resume."
        )

    @classmethod
    def cleanup_shared_client(cls): pass
