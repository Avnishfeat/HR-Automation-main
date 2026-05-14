# app/services/analysis/transcript_analyzer.py
import logging
import re
import json
from typing import Dict, Any, Optional
from pathlib import Path

from .analysis_base import BaseAnalyzer
from app.agents.interview.config.prompt_templates import PromptTemplates

logger = logging.getLogger(__name__)

class TranscriptAnalyzer(BaseAnalyzer):
    def __init__(self):
        super().__init__(
            model_name="gemini-2.5-flash",
            temperature=0.3,
            safety_level="BLOCK_NONE"
        )

    def analyze(self, session_id: str, transcript_text: str = None, resume_text: str = "Not provided", job_role: str = "Candidate") -> Dict[str, Any]:
        logger.info(f"Starting transcript analysis for {session_id}")
        try:
            if not transcript_text:
                path = Path("data") / session_id / "transcript.txt"
                if path.exists():
                    transcript_text = path.read_text(encoding="utf-8")

            if not transcript_text:
                return self._create_fallback_analysis("Transcript not found")

            prompt = self._create_prompt(
                transcript_text=transcript_text,
                resume_text=resume_text,
                job_role=job_role
            )

            response = self._call_gemini_api([prompt], expected_format="text")
            if not response or not response.get("success"):
                return self._create_fallback_analysis("Gemini failed")

            analysis_result = self._parse_analysis(response.get("data", ""))
            self._save_analysis(session_id, analysis_result)
            return analysis_result
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return self._create_fallback_analysis(str(e))

    def _create_prompt(
        self,
        transcript_text: str,
        resume_text: str = "Not provided",
        job_role: str = "Candidate"
    ) -> str:
        return PromptTemplates.hr_transcript_analysis(
            transcript_text=transcript_text,
            resume_excerpt=resume_text[:2000],
            job_role=job_role
        )

    def _parse_analysis(self, text: str) -> Dict[str, Any]:
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
            "hiring_decision": "Review Required",
            "raw_analysis": text or ""
        }

        if not text:
            return sections

        header_map = {
            "overall performance": "overall_performance",
            "authenticity check": "authenticity_analysis",
            "authenticity": "authenticity_analysis",
            "communication": "communication_skills",
            "cultural fit": "cultural_fit",
            "strengths": "strengths",
            "weaknesses": "weaknesses",
            "concerns": "weaknesses",
            "recommendations": "recommendations",
            "hiring decision": "hiring_decision",
        }

        current_section = "overall_performance"
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            line_key = line.lower().strip("#*: ")
            matched_section = None
            for header, section in header_map.items():
                if line_key.startswith(header):
                    matched_section = section
                    break

            if matched_section:
                current_section = matched_section
                remainder = re.sub(r"^[#*\s]*[^:]+:?", "", line).strip()
                if remainder and current_section not in {"strengths", "weaknesses", "recommendations"}:
                    sections[current_section] += remainder + "\n"
                continue

            if current_section in {"strengths", "weaknesses", "recommendations"}:
                item = line.lstrip("-*•0123456789. ").strip()
                if item:
                    sections[current_section].append(item)
            else:
                sections[current_section] += line + "\n"

            if current_section == "authenticity_analysis":
                score_match = re.search(r"score[:\s]*(\d+(?:\.\d+)?)", line, re.IGNORECASE)
                if score_match:
                    sections["authenticity_score"] = float(score_match.group(1))
                if "scripted" in line.lower() or "ai-generated" in line.lower():
                    sections["is_scripted"] = True

        for key in ["overall_performance", "authenticity_analysis", "communication_skills", "cultural_fit", "hiring_decision"]:
            sections[key] = sections[key].strip()

        if not sections["overall_performance"]:
            sections["overall_performance"] = text[:500]

        return sections

    def _save_analysis(self, session_id: str, analysis: Dict[str, Any]):
        path = Path("data") / session_id / "reports" / "transcript_analysis.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(analysis, f, indent=4)

    def _create_fallback_analysis(self, msg: str) -> Dict[str, Any]:
        return {
            "overall_performance": f"Error: {msg}",
            "authenticity_analysis": "Unavailable",
            "authenticity_score": 0.0,
            "is_scripted": False,
            "communication_skills": "Unavailable",
            "cultural_fit": "Unavailable",
            "strengths": [],
            "weaknesses": [msg],
            "recommendations": [],
            "hiring_decision": "No",
            "raw_analysis": msg
        }
