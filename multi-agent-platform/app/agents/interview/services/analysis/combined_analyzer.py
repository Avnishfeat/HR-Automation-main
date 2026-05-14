# app/services/analysis/combined_analyzer.py
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from PIL import Image
import io

from .analysis_base import BaseAnalyzer, FileUploadMixin
from app.agents.interview.config.constants import StoragePaths
from app.agents.interview.config.prompt_templates import PromptTemplates
from app.agents.interview.models.analysis_schemas import (
    CombinedAnalysisReport,
    VoiceDetectionReport, ScoringMetadata
)
from .voice_detector import VoiceDetector
from .gender_detector import GenderDetector
from .transcript_analyzer import TranscriptAnalyzer

logger = logging.getLogger(__name__)

class CombinedAnalyzer(BaseAnalyzer, FileUploadMixin):
    def __init__(self):
        super().__init__(
            model_name="gemini-2.5-flash",
            temperature=0.1,
            safety_level="BLOCK_ONLY_HIGH"
        )
        self.voice_detector = VoiceDetector()
        self.gender_detector = GenderDetector()
        self.transcript_analyzer = TranscriptAnalyzer()
        logger.info("CombinedAnalyzer initialized (Stateless)")

    def perform_behavioral_analysis(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            logger.info(f"Starting behavioral analysis for {session_id}")
            snapshot_dir = Path(StoragePaths.DATA_ROOT) / session_id / StoragePaths.CAPTURED_IMAGES_DIR
            if not snapshot_dir.exists():
                logger.warning(f"No snapshot directory found for {session_id}")
                return None

            snapshot_files = sorted(list(snapshot_dir.glob("*.jpg")))
            if not snapshot_files:
                return None

            images = []
            for f in snapshot_files:
                try:
                    images.append(Image.open(f))
                except Exception as e:
                    logger.warning(f"Failed to load image {f}: {e}")

            if not images: return None

            prompt = PromptTemplates.behavioral_screening(len(images))
            content = [prompt] + images
            response = self._call_gemini_api(content, expected_format="json")

            if not response["success"]: return None

            result = {
                "status": "success",
                "session_id": session_id,
                "analysis_timestamp": self._get_timestamp(),
                "total_snapshots": len(images),
                "metrics": response["data"],
                "raw_response": response.get("raw_response", "")
            }

            report_dir = Path(StoragePaths.DATA_ROOT) / session_id / "reports" / "behavioral_analysis"
            report_dir.mkdir(parents=True, exist_ok=True)
            self._save_json_file(result, report_dir / "analysis_complete.json")
            return result
        except Exception as e:
            logger.error(f"Behavioral analysis failed: {e}")
            return None

    def perform_voice_authenticity_analysis(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self.voice_detector.analyze_voice_authenticity(session_id)
        except Exception as e:
            logger.error(f"Voice analysis error: {e}")
            return None

    def combine_analyses(
        self,
        behavioral_result: Optional[Dict],
        transcript_result: Optional[Dict],
        voice_result: Optional[Dict],
        session_id: str,
        candidate_name: str = "",
        background_person_count: int = 0,
        reconnection_count: int = 0,
    ) -> CombinedAnalysisReport:
        logger.info(f"Combining analyses for session: {session_id}")

        if not transcript_result:
            transcript_result = self.transcript_analyzer.analyze(session_id)

        if not voice_result:
            voice_result = self.perform_voice_authenticity_analysis(session_id)

        scores = self._extract_all_scores(behavioral_result, transcript_result, voice_result)
        final_score, metadata = self._calculate_weighted_score(scores)

        snapshot_dir = Path(StoragePaths.DATA_ROOT) / session_id / StoragePaths.CAPTURED_IMAGES_DIR
        expected_gender, gender_conf, gender_source = self.gender_detector.detect_expected_gender(
            candidate_name, snapshot_dir
        )

        detected_voice_gender = "uncertain"
        detection_result = self._get_voice_detection_result(voice_result)
        if detection_result:
            detected_voice_gender = detection_result.get("voice_gender", {}).get("detected_gender", "uncertain")

        report = self._build_combined_report(
            session_id, scores, final_score,
            metadata, behavioral_result, transcript_result, voice_result,
            background_person_count, reconnection_count,
            expected_gender, gender_source, detected_voice_gender
        )

        # Save locally
        report_path = Path("data") / session_id / "reports" / "final_screening_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(report_path, "w") as f:
            json.dump(report.model_dump() if hasattr(report, 'model_dump') else report, f, indent=4)

        return report

    def _get_voice_detection_result(self, voice_result: Optional[Dict]) -> Optional[Dict]:
        if not voice_result: return None
        res = voice_result.get("detection_result")
        return res[0] if isinstance(res, list) and res else res if isinstance(res, dict) else None

    def _extract_all_scores(self, behavioral, transcript, voice) -> Dict[str, Optional[float]]:
        scores = {"behavioral": None, "transcript_overall": 5.0, "transcript_communication": 5.0, "transcript_cultural_fit": 5.0, "voice": None}
        if behavioral and behavioral.get("status") == "success":
            scores["behavioral"] = self._validate_score(behavioral.get("metrics", {}).get("screening_outcome", {}).get("overall_confidence_score"))
        if transcript:
            scores["transcript_overall"] = self._extract_score_from_text(transcript.get("overall_performance", ""))
            scores["transcript_communication"] = self._extract_score_from_text(transcript.get("communication_skills", ""))
            scores["transcript_cultural_fit"] = self._extract_score_from_text(transcript.get("cultural_fit", ""))
        v_res = self._get_voice_detection_result(voice)
        if v_res:
            scores["voice"] = self._convert_voice_verdict_to_score(v_res.get("overall_assessment", {}))
        return scores

    def _extract_score_from_text(self, text: str) -> float:
        import re
        if not text: return 5.0
        match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', text)
        if match: return float(match.group(1))
        return 5.0

    def _convert_voice_verdict_to_score(self, assessment: Dict) -> float:
        verdict = assessment.get("verdict", "").lower()
        if "authentic" in verdict: return 9.0
        if "likely_human" in verdict: return 7.0
        if "synthetic" in verdict: return 1.0
        return 5.0

    def _calculate_weighted_score(self, scores) -> tuple[float, ScoringMetadata]:
        weights = {"behavioral": 0.3, "transcript": 0.6, "voice": 0.1}
        transcript_comp = (scores["transcript_communication"] + scores["transcript_cultural_fit"]) / 2
        final_score = (scores["behavioral"] or 5.0) * weights["behavioral"] + transcript_comp * weights["transcript"] + (scores["voice"] or 5.0) * weights["voice"]
        metadata = ScoringMetadata(behavioral_weight=0.3, transcript_weight=0.6, voice_weight=0.1, communication_weight=0.5, technical_weight=0.5, confidence_level="high", data_quality_score=1.0)
        return round(final_score, 1), metadata

    def _build_combined_report(self, session_id, scores, final_score, metadata, behavioral, transcript, voice, bg_count, rec_count, exp_gender, exp_source, det_voice_gender) -> CombinedAnalysisReport:
        return CombinedAnalysisReport(
            session_id=session_id,
            interview_date=self._get_timestamp(),
            behavioral_score=scores["behavioral"],
            transcript_overall_score=scores["transcript_overall"],
            transcript_communication_score=scores["transcript_communication"],
            transcript_technical_score=scores["transcript_cultural_fit"],
            voice_authenticity_score=scores["voice"],
            final_weighted_score=final_score,
            scoring_metadata=metadata,
            behavioral_summary=behavioral.get("metrics", {}).get("screening_outcome", {}).get("summary") if behavioral else None,
            transcript_summary=transcript.get("overall_performance") if transcript else None,
            combined_strengths=[], combined_weaknesses=[], combined_recommendations=[],
            background_person_detection_count=bg_count,
            reconnection_count=rec_count,
            expected_gender=exp_gender,
            expected_gender_source=exp_source,
            detected_voice_gender=det_voice_gender,
            voice_gender_mismatch=(exp_gender != "uncertain" and det_voice_gender != "uncertain" and exp_gender != det_voice_gender)
        )

    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
    def analyze(self, *args, **kwargs): pass
    def _create_prompt(self, *args, **kwargs): pass
