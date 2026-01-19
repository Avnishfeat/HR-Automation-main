
import logging
import re
from typing import Dict, Any, Optional
from datetime import datetime

from app.agents.interview_agent.analysis.analysis_base import BaseAnalyzer
from app.agents.interview_agent.llm.prompt_templates import PromptTemplates
from app.core.ports.session_repository import SessionRepository

logger = logging.getLogger(__name__)

class TranscriptAnalyzer(BaseAnalyzer):
    def __init__(self, db_handler: SessionRepository):
        super().__init__(
            model_name="gemini-2.5-flash",
            temperature=0.3,
            safety_level="BLOCK_NONE"
        )
        self.db = db_handler

    def analyze(self, session_id: str) -> Dict[str, Any]:
        logger.info(f"Starting transcript analysis for {session_id}...")
        
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # 1. Fetch Session Data (Async wrapper)
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self.db.get_full_session(session_id), loop)
                session_data = future.result()
            else:
                session_data = loop.run_until_complete(self.db.get_full_session(session_id))
            
            if not session_data:
                return self._create_fallback_analysis(f"Session {session_id} not found")

            # --- NEW: CHECK FOR MALPRACTICE / TERMINATION FIRST ---
            # If the session was terminated due to malpractice, return that immediately.
            # This handles cases where transcript/audio might be empty.
            malpractice = session_data.get('malpractice_incident')
            termination_reason = session_data.get('termination_reason')
            
            # Check explicit malpractice object or specific termination strings
            is_malpractice_term = termination_reason and any(x in str(termination_reason).lower() for x in ['malpractice', 'multiple', 'integrity', 'fake'])
            
            if malpractice or is_malpractice_term:
                logger.warning(f"Malpractice detected for {session_id}. generating violation report.")
                return self._create_malpractice_analysis(malpractice or termination_reason)
            # ------------------------------------------------------

            # 2. Fetch Transcript Text
            transcript_text = None
            if hasattr(self.db, 'get_transcript_text'):
                # transcript_text = self.db.get_transcript_text(session_id)
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self.db.get_transcript_text(session_id), loop)
                    transcript_text = future.result()
                else:
                    transcript_text = loop.run_until_complete(self.db.get_transcript_text(session_id))
            
            if not transcript_text:
                transcript_text = session_data.get('transcript_text') or session_data.get('transcript')

            resume_text = session_data.get('resume_text', 'Not provided')[:2000]
            job_role = session_data.get('job_role', 'Candidate')

            if not transcript_text:
                return self._create_fallback_analysis(f"No transcript text found for {session_id}")

            # 3. Standard Analysis (Gemini)
            prompt = PromptTemplates.hr_transcript_analysis(
                transcript_text=transcript_text,
                resume_excerpt=resume_text,
                job_role=job_role
            )
            
            response = self._call_gemini_api([prompt], expected_format="text")
            
            if not response or not response.get("success"):
                error = response.get("error", "Unknown API error") if response else "No response"
                return self._create_fallback_analysis(f"Gemini API Failed: {error}")

            response_text = response.get("data", "") or response.get("raw_response", "")

            # 4. Parse & Save
            analysis_result = self._parse_analysis(response_text)
            self._save_analysis(session_id, analysis_result)
            
            return analysis_result

        except Exception as e:
            logger.error(f"Analysis failed for {session_id}: {e}", exc_info=True)
            return self._create_fallback_analysis(str(e))

    def _create_malpractice_analysis(self, incident_info: Any) -> Dict[str, Any]:
        """Generates a structured analysis report for malpractice sessions."""
        reason = "Integrity Violation"
        details = "The interview was terminated early by the system."
        
        if isinstance(incident_info, dict):
            reason = incident_info.get('type', reason).replace('_', ' ').title()
            details = f"Reason: {incident_info.get('reason', 'N/A')}. Count: {incident_info.get('participant_count', 'N/A')}"
        elif isinstance(incident_info, str):
            reason = incident_info.replace('_', ' ').title()

        return {
            "overall_performance": f" INTERVIEW TERMINATED: {reason}. Score: 0/10",
            "authenticity_analysis": f"CRITICAL FLAG: {reason}. {details}",
            "authenticity_score": 0.0,
            "is_scripted": True, # Flagged as synthetic/invalid
            "communication_skills": "N/A - Session Terminated due to Integrity Violation.",
            "cultural_fit": "N/A - Candidate Disqualified.",
            "strengths": [],
            "weaknesses": [f"Integrity Violation: {reason}", "Terminated Early"],
            "recommendations": ["DO NOT HIRE", "Flag for Future Applications"],
            "hiring_decision": "No (Malpractice)",
            "raw_analysis": f"System Malpractice Flag: {incident_info}"
        }

    # ... (Keep existing _parse_analysis, _save_analysis, _create_fallback_analysis) ...
    def _parse_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """Parses Markdown response into structured dict."""
        sections = {
            "overall_performance": "",
            "authenticity_analysis": "",
            "authenticity_score": 10.0,
            "is_scripted": False,
            "communication_skills": "",
            "cultural_fit": "",
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "hiring_decision": "",
            "raw_analysis": analysis_text
        }
        
        if not analysis_text: return sections

        current_section = None
        lines = analysis_text.split('\n')
        
        header_map = {
            "## overall performance": "overall_performance",
            "## authenticity check": "authenticity_analysis",
            "## communication": "communication_skills",
            "## cultural fit": "cultural_fit",
            "## strengths": "strengths",
            "## weaknesses": "weaknesses",
            "## concerns": "weaknesses",
            "## recommendations": "recommendations",
            "## hiring decision": "hiring_decision"
        }

        for line in lines:
            line_clean = line.strip()
            line_lower = line_clean.lower()
            
            found_header = False
            for header_txt, section_key in header_map.items():
                if header_txt in line_lower:
                    current_section = section_key
                    found_header = True
                    remaining = line_clean.replace(header_txt, "").replace(header_txt.upper(), "").strip(" :#*")
                    if remaining and current_section not in ["strengths", "weaknesses", "recommendations"]:
                        sections[current_section] += remaining + "\n"
                    break
            
            if found_header: continue

            if current_section and line_clean:
                if current_section == "authenticity_analysis":
                    sections[current_section] += line_clean + "\n"
                    if "score:" in line_lower:
                        try:
                            score_str = re.search(r"score:\s*(\d+)", line_lower)
                            if score_str:
                                sections["authenticity_score"] = float(score_str.group(1))
                                if sections["authenticity_score"] < 6:
                                    sections["is_scripted"] = True
                        except: pass
                    if "flag:" in line_lower and "true" in line_lower:
                        sections["is_scripted"] = True

                elif current_section in ["strengths", "weaknesses", "recommendations"]:
                    clean_item = line_clean.lstrip('-*•0123456789. ')
                    if clean_item: sections[current_section].append(clean_item)
                else:
                    sections[current_section] += line_clean + "\n"
        
        for key in ["overall_performance", "communication_skills", "cultural_fit", "hiring_decision", "authenticity_analysis"]:
            if isinstance(sections[key], str):
                sections[key] = sections[key].strip()
        
        return sections

    def _save_analysis(self, session_id: str, analysis: Dict[str, Any]) -> None:
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if hasattr(self.db, 'save_analysis_result'):
                # self.db.save_analysis_result(session_id, analysis)
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self.db.save_analysis_result(session_id, analysis), loop)
                    future.result()
                else:
                    loop.run_until_complete(self.db.save_analysis_result(session_id, analysis))

            logger.info(f"Saved transcript analysis for {session_id}")
        except Exception as e:
            logger.error(f"Failed to save analysis: {e}")

    def _create_fallback_analysis(self, error_msg: str) -> Dict[str, Any]:
        return {
            "overall_performance": "Analysis Failed",
            "strengths": [],
            "weaknesses": [f"Error: {error_msg}"],
            "recommendations": [],
            "hiring_decision": "No",
            "raw_analysis": error_msg
        }

    def _create_prompt(self, *args, **kwargs): raise NotImplementedError
