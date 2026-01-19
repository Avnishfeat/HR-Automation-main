
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from PIL import Image

from app.agents.interview_agent.analysis.analysis_base import BaseAnalyzer, FileUploadMixin
from app.agents.interview_agent.llm.prompt_templates import PromptTemplates
from app.models.analysis_schemas import (
    OverallAnalysis, CombinedAnalysisReport, 
    VoiceDetectionReport, ScoringMetadata
)
from app.agents.interview_agent.analysis.voice_detector import VoiceDetector
from app.agents.interview_agent.analysis.gender_detector import GenderDetector
from app.core.ports.session_repository import SessionRepository
from app.agents.interview_agent.analysis.transcript_analyzer import TranscriptAnalyzer

logger = logging.getLogger(__name__)


class CombinedAnalyzer(BaseAnalyzer, FileUploadMixin):
    def __init__(self, db_handler: Optional[SessionRepository] = None):
        super().__init__(
            model_name="gemini-2.5-flash",
            temperature=0.1,
            safety_level="BLOCK_ONLY_HIGH"
        )
        
        self.db = db_handler
        
        # --- UPDATED: Pass db_handler to VoiceDetector ---
        # This allows VoiceDetector to retrieve audio from MongoDB GridFS
        self.voice_detector = VoiceDetector(db_handler)
        self.gender_detector = GenderDetector()
        
        self.transcript_analyzer = TranscriptAnalyzer(db_handler) if db_handler else None
        
        if self.db:
            logger.info("Database connection linked to CombinedAnalyzer")
        else:
            logger.warning("No DBHandler provided; results won't be saved to DB")
    
    # =========================================================================
    # BEHAVIORAL ANALYSIS
    # =========================================================================
    
    def perform_behavioral_analysis(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Analyzes interview behavior from snapshots."""
        try:
            logger.info(f"Starting behavioral analysis for {user_id}/{session_id}")
            
            # Primary location: captured_frames/{session_id} (where MeetSessionManager saves)
            snapshot_dir = Path("captured_frames") / session_id
            
            # Fallback: data/{user_id}/{session_id}/snapshots (legacy path)
            if not snapshot_dir.exists():
                snapshot_dir = Path("data") / user_id / session_id / "snapshots"
            
            if not snapshot_dir.exists():
                logger.warning(f"Snapshot dir not found: {snapshot_dir}")
                return None
            
            # Try both filename patterns
            snapshot_files = sorted(snapshot_dir.glob("snap_*.jpg"))
            if not snapshot_files:
                snapshot_files = sorted(snapshot_dir.glob("snapshot_*.jpg"))
            
            if not snapshot_files:
                logger.warning("No snapshots found")
                return None
            
            logger.info(f"Found {len(snapshot_files)} snapshots")
            
            images = self._load_images(snapshot_files)
            
            if not images:
                return None
            
            prompt = PromptTemplates.behavioral_screening(len(images))
            
            content = [prompt] + images
            response = self._call_gemini_api(content, expected_format="json")
            
            if not response["success"]:
                return None
            
            result = {
                "status": "success",
                "user_id": user_id,
                "session_id": session_id,
                "analysis_timestamp": self._get_timestamp(),
                "total_snapshots": len(images),
                "metrics": response["data"],
                "raw_response": response.get("raw_response", "")
            }
            
            report_dir = self._get_report_directory(user_id, session_id, "behavioral_analysis")
            self._save_json_file(result, report_dir / "analysis_complete.json")
            
            logger.info("Behavioral analysis completed")
            return result
            
        except Exception as e:
            logger.error(f"Behavioral analysis failed: {e}")
            return None
    
    def _load_images(self, file_paths: List[Path]) -> List[Image.Image]:
        """Loads images from file paths."""
        images = []
        for path in file_paths:
            try:
                images.append(Image.open(path))
            except Exception:
                pass
        return images
    
    # =========================================================================
    # VOICE ANALYSIS
    # =========================================================================
    
    def perform_voice_authenticity_analysis(
        self, 
        user_id: str, 
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Delegates to VoiceDetector with enhanced path checking."""
        if not self.voice_detector:
            self.voice_detector = VoiceDetector(self.db)

        try:
            # Note: VoiceDetector now handles fetching from DB if local files are missing
            logger.info(f"Triggering Voice Authenticity Analysis for {session_id}")
            return self.voice_detector.analyze_voice_authenticity(user_id, session_id)
        except Exception as e:
            logger.error(f"Voice analysis error: {e}", exc_info=True)
            return None
    
    def _get_voice_detection_result(self, voice_result: Optional[Dict]) -> Optional[Dict]:
        """Safely extracts detection_result from voice analysis, handling list or dict format."""
        if not voice_result:
            return None
        
        detection_result = voice_result.get("detection_result")
        if detection_result is None:
            return None
        
        # Handle case where detection_result is a list (from per-file analysis)
        if isinstance(detection_result, list):
            if len(detection_result) > 0 and isinstance(detection_result[0], dict):
                # Return the first item if it's a list of dicts
                return detection_result[0]
            return None
        
        # Normal case: detection_result is already a dict
        if isinstance(detection_result, dict):
            return detection_result
        
        return None
    
    # =========================================================================
    # COMBINED ANALYSIS & SCORING (HR SCREENING)
    # =========================================================================
    
    def combine_analyses(
        self,
        behavioral_result: Optional[Dict],
        transcript_result: Optional[Dict],
        voice_result: Optional[Dict],
        session_id: str,
        candidate_id: str,
        candidate_name: str = "",
        background_person_count: int = 0,
        reconnection_count: int = 0,
    ) -> CombinedAnalysisReport:
        """
        Main entry point for generating the final HR screening report.
        ENSURES transcript analysis happens BEFORE combining.
        
        Args:
            background_person_count: Number of frames where additional persons were detected
            reconnection_count: Number of times candidate disconnected and rejoined
        """
        logger.info(f"Combining HR screening analyses for session: {session_id}")
        
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # =========================================================================
        # STEP 1: MANDATORY TRANSCRIPT ANALYSIS
        # =========================================================================
        if not transcript_result:
            logger.warning(f"Transcript result missing for {session_id}.")
            
            # First, try to retrieve existing analysis
            if self.transcript_analyzer:
                logger.info(f"Checking for existing transcript analysis...")
                try:
                    # existing_analysis = self.transcript_analyzer.get_analysis(session_id)
                    # TranscriptAnalyzer doesn't have get_analysis method explicitly, 
                    # but maybe it means fetching from DB manually?
                    # Ah, `transcript_analyzer.py` doesn't have `get_analysis`. 
                    # Assuming it relies on DB call.
                    if self.db and hasattr(self.db, 'get_analysis_report'):
                         # existing_report = self.db.get_analysis_report(session_id)
                         if loop.is_running():
                             future = asyncio.run_coroutine_threadsafe(self.db.get_analysis_report(session_id), loop)
                             existing_report = future.result()
                         else:
                             existing_report = loop.run_until_complete(self.db.get_analysis_report(session_id))
                         
                         if existing_report and isinstance(existing_report, dict) and "overall_performance" in existing_report:
                             transcript_result = existing_report
                             logger.info(f"Found existing transcript analysis in database")
                except Exception as e:
                    logger.error(f"Error retrieving existing analysis: {e}")
            
            # If still no result, run NEW analysis
            if not transcript_result and self.transcript_analyzer:
                logger.info(f"Running NEW transcript analysis for {session_id}...")
                try:
                    transcript_result = self.transcript_analyzer.analyze(session_id)
                    
                    if transcript_result:
                        logger.info("Transcript analysis completed successfully")
                    else:
                        logger.error("Transcript analysis returned None")
                except Exception as e:
                    logger.error(f"Transcript analysis failed: {e}", exc_info=True)
        else:
            logger.info("Transcript result already provided, skipping analysis")

        # =========================================================================
        # STEP 2: MANDATORY VOICE ANALYSIS
        # =========================================================================
        if not voice_result:
            logger.warning(f"Voice result missing for {session_id}.")
            
            # Check if voice analysis already exists in a combined report
            if self.db:
                try:
                    # existing_report = self.db.get_analysis_report(session_id)
                    if loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(self.db.get_analysis_report(session_id), loop)
                        existing_report = future.result()
                    else:
                        existing_report = loop.run_until_complete(self.db.get_analysis_report(session_id))

                    if existing_report and isinstance(existing_report, dict):
                        if "voice_authenticity_analysis" in existing_report:
                            voice_result = existing_report["voice_authenticity_analysis"]
                            logger.info(f"Found existing voice analysis in database")
                except Exception as e:
                    logger.error(f"Error checking for existing voice analysis: {e}")
            
            # If still no result, run NEW analysis
            if not voice_result:
                logger.info(f"Running NEW voice analysis for {session_id}...")
                try:
                    voice_result = self.perform_voice_authenticity_analysis(candidate_id, session_id)
                    if voice_result:
                        logger.info(" Voice analysis completed successfully")
                    else:
                        logger.warning(" Voice analysis returned None (check audio files)")
                except Exception as e:
                    logger.error(f"Voice analysis failed: {e}", exc_info=True)
        else:
            logger.info(" Voice result already provided, skipping analysis")


        logger.info("Extracting scores from analysis results...")
        scores = self._extract_all_scores(
            behavioral_result, transcript_result, voice_result
        )
        
        logger.info(f"Extracted scores: {scores}")

        final_score, metadata = self._calculate_weighted_score(scores)
        logger.info(f"Calculated final weighted score: {final_score}")
        

        snapshot_dir = Path("captured_frames") / session_id
        expected_gender, gender_conf, gender_source = self.gender_detector.detect_expected_gender(
            candidate_name, snapshot_dir
        )
        logger.info(f"Expected gender: {expected_gender} (source: {gender_source}, conf: {gender_conf})")
        

        detected_voice_gender = "uncertain"
        detection_result = self._get_voice_detection_result(voice_result)
        if detection_result:
            voice_gender_data = detection_result.get("voice_gender", {})
            detected_voice_gender = voice_gender_data.get("detected_gender", "uncertain")
            logger.info(f"Detected voice gender: {detected_voice_gender}")
        
        report = self._build_combined_report(
            session_id, candidate_id, scores, final_score, 
            metadata, behavioral_result, transcript_result, voice_result,
            background_person_count, reconnection_count,
            expected_gender, gender_source, detected_voice_gender
        )
        
        logger.info(" Combined report built successfully")
        
        if self.db:
            try:
                db_data = report.model_dump() if hasattr(report, 'model_dump') else report.dict()
                # self.db.save_analysis_result(session_id, db_data)
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self.db.save_analysis_result(session_id, db_data), loop)
                    future.result()
                else:
                    loop.run_until_complete(self.db.save_analysis_result(session_id, db_data))

                logger.info(f"Combined report saved to database for {session_id}")
            except Exception as e:
                logger.error(f"Failed to save combined report: {e}", exc_info=True)
        
        return report
    
    def _extract_all_scores(
        self,
        behavioral: Optional[Dict],
        transcript: Optional[Dict],
        voice: Optional[Dict]
    ) -> Dict[str, Optional[float]]:
        """Extracts scores from all analysis types for HR screening."""
        scores = {
            "behavioral": None,
            "transcript_overall": 5.0,
            "transcript_communication": 5.0,
            "transcript_cultural_fit": 5.0,
            "voice": None
        }
        
        # Behavioral score
        if behavioral and behavioral.get("status") == "success":
            metrics = behavioral.get("metrics", {})
            screening = metrics.get("screening_outcome", {})
            scores["behavioral"] = self._validate_score(
                screening.get("overall_confidence_score"), default=None
            )
        
        # Transcript scores (HR screening focused)
        if transcript:
            # Overall performance score
            overall_text = transcript.get("overall_performance", "")
            scores["transcript_overall"] = self._extract_score_from_text(overall_text)
            
            # Communication skills score
            comm_text = transcript.get("communication_skills", "")
            scores["transcript_communication"] = self._extract_score_from_text(comm_text)
            
            # Cultural fit score
            fit_text = transcript.get("cultural_fit", "")
            scores["transcript_cultural_fit"] = self._extract_score_from_text(fit_text)

        # Voice score
        detection_result = self._get_voice_detection_result(voice)
        if detection_result:
            assessment = detection_result.get("overall_assessment", {})
            scores["voice"] = self._convert_voice_verdict_to_score(assessment)
        
        return scores
    
    def _extract_score_from_text(self, text: str) -> float:
        """
        Extracts numeric score from descriptive text.
        """
        if not text:
            return 5.0
        
        import re
        
        # Look for X/10 pattern
        match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', text)
        if match:
            return float(match.group(1))
        
        # Look for "score: X" pattern
        match = re.search(r'score:\s*(\d+(?:\.\d+)?)', text.lower())
        if match:
            return float(match.group(1))
        
        # Qualitative assessment
        text_lower = text.lower()
        if any(word in text_lower for word in ['excellent', 'outstanding', 'exceptional']):
            return 9.0
        elif any(word in text_lower for word in ['very good', 'strong', 'impressive']):
            return 8.0
        elif any(word in text_lower for word in ['good', 'solid', 'competent']):
            return 7.0
        elif any(word in text_lower for word in ['satisfactory', 'adequate', 'fair']):
            return 6.0
        elif any(word in text_lower for word in ['below average', 'weak', 'concerning']):
            return 4.0
        elif any(word in text_lower for word in ['poor', 'inadequate', 'unacceptable']):
            return 3.0
        
        return 5.0  # Default neutral
    
    def _convert_voice_verdict_to_score(self, assessment: Dict) -> Optional[float]:
        """Converts voice authenticity verdict to 0-10 score."""
        verdict = assessment.get("verdict", "").lower()
        confidence_pct = assessment.get("confidence_percentage", 50)
        
        verdict_map = {
            "authentic": (8.0, 10.0),
            "likely_human": (6.0, 8.0),
            "uncertain": (5.0, 5.0),
            "likely_synthetic": (2.0, 5.0),
            "synthetic": (0.0, 2.0)
        }
        
        for key, (min_score, max_score) in verdict_map.items():
            if key in verdict:
                range_size = max_score - min_score
                score = min_score + (confidence_pct / 100.0) * range_size
                return self._validate_score(score)
        
        return 5.0
    
    def _calculate_weighted_score(
        self,
        scores: Dict[str, Optional[float]]
    ) -> tuple[float, ScoringMetadata]:
        """Calculates final weighted score for HR screening."""
        
        # --- NEW: DETECT MALPRACTICE KILL SWITCH ---
        # If any major component is exactly 0.0 (and not None), it implies a forced failure/malpractice.
        is_malpractice = (
            (scores["transcript_overall"] is not None and scores["transcript_overall"] == 0.0) or 
            (scores["voice"] is not None and scores["voice"] == 0.0)
        )
        
        if is_malpractice:
            logger.warning("Zero score detected (Malpractice). Forcing final score to 0.0")
            metadata = ScoringMetadata(
                behavioral_weight=0, transcript_weight=0, voice_weight=0,
                communication_weight=0, technical_weight=0,
                confidence_level="high", # We are highly confident they failed
                data_quality_score=1.0
            )
            return 0.0, metadata
        # -------------------------------------------

        # HR screening weights
        weights = {
            "behavioral": 0.3,
            "transcript": 0.6,
            "voice": 0.1
        }
        
        # Calculate transcript composite (communication + cultural fit)
        transcript_composite = (
            scores["transcript_communication"] * 0.5 + 
            scores["transcript_cultural_fit"] * 0.5
        )
        
        # Collect available scores
        available = {}
        if scores["behavioral"] is not None:
            available["behavioral"] = (scores["behavioral"], weights["behavioral"])
        
        if scores["transcript_overall"] is not None:
            available["transcript"] = (transcript_composite, weights["transcript"])
            
        if scores["voice"] is not None:
            available["voice"] = (scores["voice"], weights["voice"])
        
        # Normalize weights
        if available:
            total_weight = sum(w for _, w in available.values())
            for key in available:
                score, weight = available[key]
                available[key] = (score, weight / total_weight)
        
        # Calculate weighted average
        final_score = sum(score * weight for score, weight in available.values()) if available else 0.0
        
        # Calculate data quality
        data_quality = len(available) / 3.0
        confidence = "high" if data_quality >= 0.8 else "medium" if data_quality >= 0.5 else "low"
        
        metadata = ScoringMetadata(
            behavioral_weight=available.get("behavioral", (0, 0))[1],
            transcript_weight=available.get("transcript", (0, 0))[1],
            voice_weight=available.get("voice", (0, 0))[1],
            communication_weight=0.5,
            technical_weight=0.5,  # Kept for schema compatibility, represents cultural fit
            confidence_level=confidence,
            data_quality_score=round(data_quality, 2)
        )
        
        return round(final_score, 1), metadata
    
    def _build_combined_report(
        self, session_id, candidate_id, scores, final_score, 
        metadata, behavioral_result, transcript_result, voice_result,
        background_person_count: int = 0,
        reconnection_count: int = 0,
        expected_gender: str = "uncertain",
        expected_gender_source: str = "none",
        detected_voice_gender: str = "uncertain"
    ) -> CombinedAnalysisReport:
        """Builds the final combined report for HR screening."""
        
        def get_list(source, key):
            if not source: return []
            if isinstance(source, dict): return source.get(key, [])
            return getattr(source, key, [])

        behavioral_summary = None
        if behavioral_result and behavioral_result.get("status") == "success":
            behavioral_summary = behavioral_result.get("metrics", {}).get("screening_outcome", {}).get("summary")

        transcript_summary = "Transcript analysis unavailable."
        if transcript_result:
            transcript_summary = transcript_result.get("overall_performance", "No summary provided.")

        # Combine strengths
        b_strengths = []
        if behavioral_result and behavioral_result.get("status") == "success":
             b_strengths = behavioral_result.get("metrics", {}).get("screening_outcome", {}).get("key_positive_traits", [])
        
        t_strengths = get_list(transcript_result, "strengths")
        combined_strengths = list(set(b_strengths + t_strengths))

        # Combine concerns/weaknesses
        b_weaknesses = []
        if behavioral_result and behavioral_result.get("status") == "success":
             b_weaknesses = behavioral_result.get("metrics", {}).get("screening_outcome", {}).get("areas_to_probe", [])
        
        t_concerns = get_list(transcript_result, "concerns")
        combined_weaknesses = list(set(b_weaknesses + t_concerns))
        
        # Recommendations
        recommendations = get_list(transcript_result, "recommendations")
        
        # Add Voice warnings if high risk
        detection_result = self._get_voice_detection_result(voice_result)
        if detection_result:
            assessment = detection_result.get("overall_assessment", {})
            if assessment.get("risk_level", "").lower() in ["high", "medium"]:
                recommendations.insert(0, f"VOICE FLAG: {assessment.get('verdict','').upper()}")

        voice_report = None
        if voice_result:
            try:
                # Normalize detection_result if it's a list
                normalized_voice = voice_result.copy()
                if isinstance(normalized_voice.get("detection_result"), list):
                    if normalized_voice["detection_result"]:
                        normalized_voice["detection_result"] = normalized_voice["detection_result"][0]
                    else:
                        normalized_voice["detection_result"] = {}
                voice_report = VoiceDetectionReport(**normalized_voice)
            except Exception as e:
                logger.warning(f"Could not parse voice result: {e}")

        # --- NEW: DETECT VOICE GENDER MISMATCH ---
        voice_gender_mismatch = False
        final_score_override = final_score
        if (expected_gender != "uncertain" and 
            detected_voice_gender != "uncertain" and
            expected_gender != detected_voice_gender):
            voice_gender_mismatch = True
            final_score_override = 0.0  # Force rejection on mismatch
            logger.warning(f"VOICE GENDER MISMATCH: Expected {expected_gender}, detected {detected_voice_gender} - SCORE SET TO 0")
            recommendations.insert(0, f"CRITICAL: VOICE GENDER MISMATCH (Expected: {expected_gender}, Detected: {detected_voice_gender}) - AUTOMATIC REJECTION")

        return CombinedAnalysisReport(
            session_id=session_id,
            candidate_id=candidate_id,
            interview_date=self._get_timestamp(),
            behavioral_score=scores["behavioral"],
            transcript_overall_score=scores["transcript_overall"],
            transcript_communication_score=scores["transcript_communication"],
            transcript_technical_score=scores["transcript_cultural_fit"],  # Reused field for cultural fit
            voice_authenticity_score=scores["voice"],
            final_weighted_score=final_score_override,
            scoring_metadata=metadata,
            confidence_interval_lower=None,
            confidence_interval_upper=None,
            behavioral_summary=behavioral_summary,
            transcript_summary=transcript_summary,
            combined_strengths=combined_strengths,
            combined_weaknesses=combined_weaknesses,
            combined_recommendations=recommendations,
            voice_authenticity_analysis=voice_report,
            background_person_detection_count=background_person_count,
            reconnection_count=reconnection_count,
            expected_gender=expected_gender,
            expected_gender_source=expected_gender_source,
            detected_voice_gender=detected_voice_gender,
            voice_gender_mismatch=voice_gender_mismatch
        )
    
    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
    
    def analyze(self, *args, **kwargs):
        raise NotImplementedError("Use perform_behavioral_analysis or combine_analyses")
    
    def _create_prompt(self, *args, **kwargs):
        raise NotImplementedError("Use PromptTemplates instead")
