# app/services/analysis/combined_analyzer.py
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import json

from .analysis_base import BaseAnalyzer, FileUploadMixin
from app.agents.interview.config.prompt_templates import PromptTemplates

logger = logging.getLogger(__name__)

class CombinedAnalyzer(BaseAnalyzer, FileUploadMixin):
    def __init__(self):
        super().__init__(
            model_name="gemini-2.5-flash",
            temperature=0.1,
            safety_level="BLOCK_ONLY_HIGH"
        )
        logger.info("CombinedAnalyzer initialized (Stateless)")

    def analyze(self, *args, **kwargs) -> Dict[str, Any]:
        """Stub to satisfy BaseAnalyzer abstract method."""
        return {}

    def _create_prompt(self, *args, **kwargs) -> str:
        """Stub to satisfy BaseAnalyzer abstract method."""
        return ""

    def generate_final_report(
        self,
        session_id: str,
        transcript_text: str,
        resume_text: str,
        job_role: str,
        candidate_name: str,
        duration_sec: int,
        ended_early: bool,
        background_person_count: int = 0,
        reconnection_count: int = 0,
        candidate_email: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            logger.info(f"Starting final combined analysis for {session_id}")
            
            prompt = PromptTemplates.final_combined_analysis(
                transcript_text=transcript_text,
                resume_excerpt=resume_text[:2000] if resume_text else "Not provided",
                job_role=job_role,
                session_id=session_id,
                candidate_name=candidate_name,
                candidate_email=candidate_email or "Not provided",
                duration_sec=duration_sec,
                ended_early=ended_early,
                reconnections=reconnection_count,
                background_persons=background_person_count
            )
            
            response = self._call_gemini_api([prompt], expected_format="json")
            if not response or not response.get("success"):
                logger.error(f"Gemini API failed for final report: {response}")
                return None
                
            result = response.get("data")
            
            # Save locally
            report_path = Path("data") / session_id / "reports" / "final_screening_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(report_path, "w") as f:
                json.dump(result, f, indent=4)
                
            return result
        except Exception as e:
            logger.error(f"Failed to generate final report: {e}", exc_info=True)
            return None
