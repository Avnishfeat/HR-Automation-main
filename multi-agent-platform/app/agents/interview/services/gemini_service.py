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

from app.agents.interview.core.ports.session_repository import SessionRepository
from app.agents.interview.core.retry_handler import retry_on_failure
from app.agents.interview.core.exceptions import (
    ExternalServiceError, 
    ServiceInitializationError,
    InterviewBotException
)

from app.agents.interview.config.prompt_templates import PromptTemplates 

logger = logging.getLogger(__name__)

class GeminiService:
    MODEL_NAME = "gemini-2.5-flash" 

    def __init__(self, db_handler: SessionRepository):
        self.db = db_handler
        self.active_chat_sessions: Dict[str, Any] = {}
        self._session_token_counts = defaultdict(lambda: {'prompt': 0, 'response': 0, 'total': 0})
        self.client = None
        
        self._initialize_client()

    def _initialize_client(self):
        """Initializes the Gemini Client (Standard Mode)."""
        try:
            # Use centralized secrets manager
            from app.agents.interview.config.secrets import secrets
            gemini_api_key = secrets.get_required("GEMINI_API_KEY")
            
            # REVERTED: Use standard initialization to fix crash.
            # The SDK manages its own connection pool efficiently by default.
            self.client = genai.Client(api_key=gemini_api_key)
            
            logger.info("✓ GeminiService: Client configured successfully.")
            
        except Exception as e:
            logger.error(f"GeminiService Initialization Failed: {e}", exc_info=True)
            self.client = None

    def _get_config(self, temperature: float = 0.0) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            temperature=temperature,
            top_k=40,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH
                ),
            ]
        )

    def _map_gemini_error(self, e: Exception, operation: str) -> InterviewBotException:
        err_str = str(e).lower()
        if "429" in err_str or "resourceexhausted" in err_str:
            return ExternalServiceError("Gemini", operation, "Rate limit exceeded", 429, retryable=True)
        if "503" in err_str or "500" in err_str or "unavailable" in err_str:
            return ExternalServiceError("Gemini", operation, "Service temporarily unavailable", 503, retryable=True)
        if "safety" in err_str or "blocked" in err_str:
             return ExternalServiceError("Gemini", operation, "Content blocked by safety filters", 400, retryable=False)
        return ExternalServiceError("Gemini", operation, f"Unexpected error: {str(e)}", retryable=False)

    @retry_on_failure(operation_name="extract_candidate_name")
    def extract_candidate_name(self, resume_text: str) -> str:
        if not self.client: raise ServiceInitializationError("Gemini", "Client not initialized")
        try:
            truncated_text = resume_text[:3000]
            prompt = f"Identify the candidate's Full Name from the resume text below.\nRules:\n1. Ignore labels like 'Project Name'.\n2. Return ONLY the name in Title Case.\n3. If not found, return 'Candidate'.\n\nRESUME TEXT:\n---\n{truncated_text}\n---\nName:"
            response = self.client.models.generate_content(
                model=self.MODEL_NAME, contents=prompt, config=self._get_config(temperature=0.0)
            )
            raw_text = response.text or ""
            name = raw_text.strip().replace('"', '').replace("'", "").replace("\n", "")
            if len(name) > 50 or " " not in name: return "Candidate"
            return name.title()
        except Exception as e: raise self._map_gemini_error(e, "extract_name")

    @retry_on_failure(operation_name="start_chat_session")
    def start_chat_session(self, session_id: str, resume_text: str, questionnaire: List[str], job_role: str, job_description: Optional[str] = None):
        if not self.client: raise ServiceInitializationError("Gemini", "Client not initialized")
        logger.info(f"GeminiService: Initializing chat for session {session_id}")
        
        system_prompt = self._build_system_prompt(resume_text, questionnaire, job_role, job_description)
        try:
            self._session_token_counts[session_id] = {'prompt': 0, 'response': 0, 'total': 0}
            history: List[Dict[str, Any]] = [
                {"role": "user", "parts": [{"text": system_prompt}]},
                {"role": "model", "parts": [{"text": "Understood. I will conduct a professional HR screening interview."}]}
            ]
            self.active_chat_sessions[session_id] = self.client.chats.create(
                model=self.MODEL_NAME, history=history, config=self._get_config(temperature=0.7)
            )
            logger.info(f"✓ GeminiService: Session {session_id} ready.")
            
            # Re-enable the simple warmup (safe version)
            threading.Thread(target=self._warmup_model, daemon=True).start()

        except Exception as e:
            if session_id in self._session_token_counts: del self._session_token_counts[session_id]
            raise self._map_gemini_error(e, "start_chat")

    def _warmup_model(self):
        """Sends a dummy request to establish the SSL/TCP connection early."""
        if not self.client: return
        try:
            # Send 1 token just to handshake
            self.client.models.generate_content(
                model=self.MODEL_NAME, 
                contents="Hi"
            )
            logger.debug("GeminiService: Connection warmed up.")
        except Exception as e:
            logger.debug(f"GeminiService: Warmup failed (non-critical): {e}")

    def stream_gemini_sentences(self, session_id: str, last_user_answer: str) -> Iterator[str]:
        chat = self.active_chat_sessions.get(session_id)
        if not chat:
            logger.error(f"GeminiService: Session {session_id} not found.")
            yield "Error: Session lost."
            return

        try:
            response_stream = chat.send_message_stream(message=last_user_answer)
            sentence_buffer = ""
            last_chunk = None
            
            for chunk in response_stream:
                last_chunk = chunk
                try:
                    text = chunk.text
                    if not text: continue
                except Exception: continue 
                
                sentence_buffer += text
                
                while True:
                    match = re.search(r'([^.!?]+[.!?])(\s+|$)', sentence_buffer)
                    if match:
                        sentence = match.group(1).strip()
                        if sentence: yield sentence
                        sentence_buffer = sentence_buffer[len(match.group(0)):].lstrip()
                    else: break
            
            if sentence_buffer.strip(): yield sentence_buffer.strip()
            
            self._log_token_usage(session_id, last_chunk)
            
        except Exception as e:
            mapped_error = self._map_gemini_error(e, "stream_response")
            logger.error(f"GeminiService: Stream failed: {mapped_error.message}")
            yield "I didn't catch that. Could you rephrase?"

    @retry_on_failure(operation_name="generate_analysis_report")
    async def generate_analysis_report(
        self, 
        transcript: List[Dict[str, Any]], 
        job_role: str,
        job_description: Optional[str] = None,
        resume_excerpt: str = ""
    ) -> Dict[str, Any]:
        """Generates a detailed JSON analysis of the interview."""
        if not self.client:
            raise ServiceInitializationError("Gemini", "Client not initialized")

        transcript_text = ""
        for turn in transcript:
            role = turn.get("role", "unknown")
            text = turn.get("text", "")
            transcript_text += f"{role.upper()}: {text}\n"

        prompt = PromptTemplates.transcript_analysis(transcript_text, resume_excerpt)
        
        try:
            response = await self.client.aio.models.generate_content(
                model=self.MODEL_NAME,
                contents=prompt,
                config=self._get_config(temperature=0.0)
            )
            
            raw_text = response.text
            if raw_text is None:
                raise ValueError("Gemini returned empty response for analysis.")

            analysis_dict = self._clean_and_parse_json(raw_text)
            return analysis_dict

        except Exception as e:
            raise self._map_gemini_error(e, "generate_analysis_report")

    def _clean_and_parse_json(self, raw_text: str) -> Dict[str, Any]:
        try:
            cleaned = re.sub(r"```json\s*|\s*```", "", raw_text).strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                start = raw_text.find("{")
                end = raw_text.rfind("}") + 1
                if start != -1 and end != -1:
                    return json.loads(raw_text[start:end])
                raise ValueError("Could not extract valid JSON from response")
            except Exception as e:
                logger.error(f"JSON Parsing failed. Raw text: {raw_text[:100]}...")
                raise ValueError(f"JSON parsing failed: {e}")

    def _log_token_usage(self, session_id, last_chunk):
        try:
            usage = getattr(last_chunk, 'usage_metadata', None)
            if usage:
                p = getattr(usage, 'prompt_token_count', 0)
                r = getattr(usage, 'candidates_token_count', 0)
                t = getattr(usage, 'total_token_count', 0)
                self._session_token_counts[session_id]['prompt'] += p
                self._session_token_counts[session_id]['response'] += r
                self._session_token_counts[session_id]['total'] += t
                self.db.update_gemini_token_usage(session_id, "interview", p, r, t)
        except Exception as e: 
            logger.warning(f"GeminiService: Token logging failed: {e}")

    def end_session(self, session_id: str):
        if session_id in self.active_chat_sessions: del self.active_chat_sessions[session_id]
        if session_id in self._session_token_counts: del self._session_token_counts[session_id]
            
    def check_api_health(self) -> bool:
        if not self.client: return False
        try:
            self.client.models.generate_content(model=self.MODEL_NAME, contents="ping")
            return True
        except Exception: return False
    
    @classmethod
    def cleanup_shared_client(cls):
        # Clean method kept for compatibility with startup.py, but does nothing now
        pass

    def _build_system_prompt(self, resume_text: str, questionnaire: List[str], job_role: str, job_description: Optional[str]) -> str:
        # (Prompt generation logic remains the same as your previous working version)
        questionnaire_context = ""
        if questionnaire: 
            questionnaire_str = "\n".join([f"- {q}" for q in questionnaire])
            questionnaire_context = f"\n**Reference Questionnaire:**\n---\n{questionnaire_str}\n---"
        else: 
            questionnaire_context = "\n**Reference Questionnaire:** Not provided."

        jd_context = ""
        if job_description:
             jd_context = f"\n**Official Job Description (JD):**\n---\n{job_description}\n---\n"
             jd_instruction = "Use the **Job Description** to understand the role requirements and assess candidate fit."
        else:
             jd_context = "\n**Official Job Description:** Not provided."
             jd_instruction = "Focus on general role expectations and the candidate's background."

        policies = """
### OFFICIAL INTERVIEW LOGISTICS & RULES
Use these facts to answer candidate questions. Do NOT deviate.
* **Camera Policy:** MANDATORY. The candidate must keep their camera ON at all times.
* **Recording:** The candidate is NOT allowed to record the session.
* **Duration:** The interview will last approximately 10-15 minutes.
* **Process:** After this HR screening, the recruiting team will review the results and reach out.
"""

        return f"""
You are an AI HR Recruiter conducting a professional **HR screening interview** for the position of **{job_role}**. 

Your role is to assess the candidate's background, career goals, motivation, cultural fit, communication skills, and basic alignment with the role. You are conducting an HR screening, NOT a technical interview.

**CRITICAL FORMATTING RULES:**
* **Raw Text Only:** Your responses MUST be raw text. Do NOT use SSML, Markdown (like `*` or `##`), asterisks, or any special formatting.
* **Natural Punctuation:** Use proper punctuation (commas, periods, question marks) as this will be used by a TTS engine to create natural speech pauses.
* **Short Start:** Always start your response with a very short sentence (under 5 words). Example: "That is great." or "I understand." Then continue with your full thought.
* **Conversational Length:** Keep your questions conversational and natural, ideally **15-25 words.**
* **One Question Only:** Ask **exactly one question** per response. Do not ask multi-part questions.
* **Professional Tone:** Maintain a warm, professional, and conversational HR tone. Be encouraging and empathetic.

---
**INTERVIEW CONTEXT:**

**Target Job Role:** {job_role}
{jd_context}

**Resume:**
---
{resume_text}
---
{questionnaire_context}

{policies}

---

### INTERVIEW STRUCTURE & TASK

Your task is to generate the next logical question in the HR screening interview.

**HR SCREENING FOCUS AREAS:**
1. **Background & Experience:** Understand their career journey, transitions, and relevant experience.
2. **Motivation & Interest:** Why they're interested in this role and company.
3. **Career Goals:** Short-term and long-term aspirations.
4. **Cultural Fit:** Work style, team collaboration, values alignment.
5. **Communication Skills:** Clarity, professionalism, and confidence in responses.
6. **Availability & Logistics:** Notice period, relocation willingness, salary expectations (if appropriate).
7. **Behavioral Questions:** Past experiences handling challenges, teamwork, conflict resolution.

**ANTI-REPETITION & TOPIC PROGRESSION RULES:**
1. **NO REPETITION:** Never ask the same or similar questions twice.
2. **NATURAL FLOW:** Progress through different HR topics smoothly. Start broad, then dive deeper.
3. **VARIETY:** Cover multiple aspects - background, motivation, goals, fit, behavioral scenarios.
4. **PROGRESSION:** - If candidate gives good answers, move to next HR topic.
    - If answers are vague, ask clarifying follow-ups.
    - Transition naturally between topics.

**INTERVIEW PHASES:**

1.  **Phase 1: Opening (Basic Profile):** The candidate's first message will be their introduction. Your first response should warmly acknowledge them.
    - Start with "Tell me about yourself." or a variation.
    - If they introduced themselves, ask: "Why are you looking for a new job right now?" or "Why do you want to change roles?"

2.  **Phase 2: Core HR Assessment:** Cycle through these key areas naturally:
    
    * **Motivation & Company Knowledge:**
        - "Why did you apply for this position and why do you want to work at our company?"
        - "What do you know about our company and our products or services?"
        
    * **Experience & Role Fit:**
        - "How does your previous experience make you a good fit for this role?"
        - "What are the most relevant projects you've worked on for this position?"
        - "What are your key strengths for this role?"
        - "What is one area you are currently trying to improve?"
        
    * **Work Style & Behavior:**
        - "How would you describe your work style and how you handle deadlines or pressure?"
        - "Tell me about a time you faced a major challenge at work and how you handled it."
        - "Tell me about a time you had a conflict with a teammate or manager and what you did."
        - "What kind of work environment do you work best in?"

3.  **Phase 3: Logistics & Culture:**
    * **Logistics (Mandatory):**
        - "What is your current role, notice period, and availability to join?"
        - "What are your salary expectations or current CTC?"
        - "Are you interviewing with other companies right now?"
        - "Are you open to remote, hybrid, or onsite work, and do you have a preferred location?"
        
    * **Goals & Closing:**
        - "Where do you see yourself in the next 3 to 5 years?"
        - "What are you looking for in your next role and team?"
        - "What motivates you in your professional life?"
        - "What did you like most and least about your previous job?"

### HANDLING DIFFERENT RESPONSE TYPES

* **If the answer is GOOD and DETAILED:**
    * Acknowledge warmly ("That's great to hear," "Thank you for sharing that," "I appreciate that perspective.") and move to the next HR topic.

* **If the answer is SHORT or VAGUE:**
    * Ask a follow-up question to encourage more detail. ("Could you tell me more about that?" "What specifically attracted you to that opportunity?")

* **If the answer is a LOGISTICAL QUESTION:**
    * Answer briefly using the OFFICIAL INTERVIEW LOGISTICS.
    * Transition back smoothly: "Now, let's continue..."
    * Ask your next interview question.

* **If the answer is "I DON'T KNOW" or NON-COMMITTAL:**
    * Acknowledge gracefully ("That's alright," "No problem.") and ask about a different HR topic.

* **If the answer is INVALID, IRRELEVANT, NONSENSICAL, or OFF-TOPIC:**
    * CRITICAL: You MUST validate that the candidate's response is relevant to the interview context and the question asked.
    * If the response contains gibberish, random words, completely unrelated topics, inappropriate content, or does not attempt to answer the question:
      - Politely but firmly remind them: "I notice your response doesn't seem to address the question. This is a professional interview, so please provide relevant answers related to your background and the position."
      - Then re-ask your previous question.
    * Examples of INVALID responses: random letters/numbers, jokes unrelated to the question, talking about completely different topics (sports, weather, random stories), intentionally avoiding the question.
    * If the candidate provides 2-3 consecutive invalid responses, escalate your warning: "I need you to provide serious, relevant answers to continue this interview. Please focus on the question asked."

---

### YOUR TASK

You will receive the full conversation history. Generate **only the raw text for your next question** based on HR screening best practices. Maintain a warm, professional, and engaging tone appropriate for an **{job_role}** HR screening interview.

**IMPORTANT:** Before generating your next question, evaluate if the candidate's last response was valid and relevant. If it was nonsensical, off-topic, or invalid, issue a warning and re-ask the question instead of proceeding.
"""