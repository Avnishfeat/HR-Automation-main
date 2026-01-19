
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List

# Import the updated schema
from app.agents.interview_agent.analysis.analysis_base import BaseAnalyzer, FileUploadMixin
from app.agents.interview_agent.llm.prompt_templates import PromptTemplates
from app.core.ports.session_repository import SessionRepository

logger = logging.getLogger(__name__)

class VoiceDetector(BaseAnalyzer, FileUploadMixin):
    """
    Detects voice authenticity and forensic anomalies using Gemini.
    """
    
    def __init__(self, db_handler: Optional[SessionRepository] = None):
        super().__init__(
            model_name="gemini-2.5-flash",
            temperature=0.1,
            # We need high safety to prevent blocking on "harassment" if the model detects bad language in background
            safety_level="BLOCK_ONLY_HIGH" 
        )
        self.db = db_handler
    
    def analyze_voice_authenticity(
        self, 
        user_id: str, 
        session_id: str,
        max_samples: int = 5
    ) -> Optional[Dict[str, Any]]:
        temp_dir = None
        try:
            # 1. Gather Audio Files (Existing logic)
            audio_files = []
            if self.db:
                audio_files = self._fetch_audio_from_db(session_id, max_samples)
                if audio_files:
                    temp_dir = audio_files[0].parent

            if not audio_files:
                # Fallback to local
                # Assuming relative path from current working directory
                # or we should use settings.UPLOAD_DIR or similar if configured.
                # For porting, keeping original relative path "data" as per legacy.
                local_dir = Path("data") / user_id / session_id / "audio"
                if local_dir.exists():
                    audio_files = sorted(local_dir.glob("candidate_turn_*_stt_24k.wav"))[:max_samples]

            if not audio_files:
                return self._create_error_result(user_id, session_id, "No audio files found")
            
            logger.info(f"Analyzing {len(audio_files)} audio samples for forensics...")
            
            # 2. Upload to Gemini
            uploaded_files = self._upload_files_to_gemini(audio_files, max_files=max_samples)
            
            if not uploaded_files:
                return self._create_error_result(user_id, session_id, "Failed to upload audio")
            
            # 3. Analyze with NEW Forensic Prompt
            # We inject a custom prompt here instead of using the generic PromptTemplates
            prompt = self._get_forensic_prompt(len(uploaded_files))
            content = [prompt] + uploaded_files
            
            response = self._call_gemini_api(content, expected_format="json")
            
            if not response["success"]:
                return self._create_error_result(user_id, session_id, response.get("error", "API call failed"))
            
            # 4. Format Result
            # The response["data"] will now match our updated VoiceAuthenticityResult schema
            result = {
                "user_id": user_id,
                "session_id": session_id,
                "analysis_timestamp": self._get_timestamp(),
                "samples_analyzed": len(audio_files),
                "detection_result": response["data"],
                "raw_response": response.get("raw_response", ""),
                "status": "success"
            }
            
            # 5. Save Report
            self._save_voice_reports(user_id, session_id, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Voice detection error: {e}", exc_info=True)
            return self._create_error_result(user_id, session_id, str(e))
        
        finally:
            if temp_dir and temp_dir.exists() and "temp_voice_analysis" in str(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _get_forensic_prompt(self, file_count: int) -> str:
        """
        Custom prompt to detect Replay Attacks, Whispering, and Voice Gender.
        """
        return f"""
        You are an expert Audio Forensics Analyst for high-stakes interviews.
        Analyze the {file_count} provided audio files.
        
        Your task is to validate the integrity of the candidate's audio environment.
        
        1. **VOICE AUTHENTICITY (Human vs AI)**:
           - Is the primary speaker a live human or a TTS engine?
           
        2. **REPLAY ATTACK DETECTION (The Edge Case)**:
           - Detect if the candidate is playing a pre-recorded file of a human (audio deepfake / playback).
           - Look for: 
             - "Speaker artifacts": The sound of a voice coming through a loudspeaker (tinny, boxy).
             - "Double Reverb": The recording has room echo, played into a room with different echo.
             - "Digital Silence": Absolute silence (digital zeros) between words, which is impossible in a live microphone setting.
             - "Discontinuity": abrupt changes in background noise floor.
             
        3. **EXTERNAL ASSISTANCE (Whisper Help)**:
           - Detect if another person is in the room helping the candidate.
           - Look for:
             - Faint whispering in the background (especially before the candidate speaks).
             - "Prompting": A quiet voice saying a keyword, followed by the candidate repeating it.
             - Two distinct voice profiles (biometrics) in the same channel.
        
        4. **VOICE GENDER DETECTION (NEW)**:
           - Determine the likely biological gender of the PRIMARY speaker based on:
             - Fundamental frequency (pitch): Male voices typically 85-180 Hz, Female voices typically 165-255 Hz
             - Voice timbre and resonance characteristics
             - Speech patterns and intonation
           - This is critical for detecting proxy interviews where someone else speaks on behalf of the candidate.
             
        Return the result in this exact JSON structure:
        {{
            "voice_authenticity": {{
                "is_human": boolean,
                "confidence_score": float (1-10),
                "classification": "human_natural" | "synthetic_robotic" | "replay_attack_suspected",
                "detection_basis": [str]
            }},
            "voice_gender": {{
                "detected_gender": "male" | "female" | "uncertain",
                "confidence": float (1-10),
                "analysis_basis": str
            }},
            "integrity_analysis": {{
                "playback_detected": boolean,
                "playback_confidence": float (1-10),
                "playback_evidence": [str],
                "whisper_detected": boolean,
                "multiple_speakers_detected": boolean,
                "whisper_confidence": float (1-10),
                "whisper_segments": [str]
            }},
            "audio_quality_analysis": {{
                "recording_quality": "poor" | "fair" | "good",
                "background_noise_level": "none" | "low" | "high",
                "clarity_score": float (1-10),
                "sample_consistency": str
            }},
            "human_characteristics_detected": {{
                "natural_prosody": boolean,
                "emotional_variance": boolean,
                "breathing_patterns": boolean,
                "natural_pauses": boolean,
                "voice_modulation": boolean
            }},
            "synthetic_indicators": {{
                "robotic_tone": boolean,
                "uniform_pitch": boolean,
                "mechanical_rhythm": boolean,
                "tts_artifacts": boolean,
                "unnatural_pacing": boolean
            }},
            "overall_assessment": {{
                "verdict": "authentic_human" | "likely_human" | "suspected_replay" | "suspected_coaching" | "synthetic",
                "confidence_percentage": float,
                "risk_level": "low" | "medium" | "high",
                "recommendation": "approve" | "flag_for_review" | "reject"
            }},
            "detailed_observations": str,
            "samples_analyzed": int
        }}
        """

    def _fetch_audio_from_db(self, session_id: str, limit: int) -> List[Path]:
        """
        Retrieves audio files from GridFS based on session transcript metadata.
        Downloads them to a temporary directory.
        """
        if not self.db: return []
        
        try:
            # Need to handle async DB access properly.
            # Assuming db_handler protocol returns coroutines if using MongoSessionRepository.
            # But here we are in a synchronous context or thread.
            # For now, simplistic event loop approach until massive architectural refactor.
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # 1. Get filenames from session transcript
            # session_data = self.db.get_full_session(session_id)
            if hasattr(self.db, 'get_full_session'):
                 if loop.is_running():
                     # If called from async code, we should await. But we are in sync function.
                     # This is the tricky part of mixed sync/async.
                     # Assuming this is run in a thread by CombinedAnalyzer usually.
                     future = asyncio.run_coroutine_threadsafe(self.db.get_full_session(session_id), loop)
                     session_data = future.result()
                 else:
                     session_data = loop.run_until_complete(self.db.get_full_session(session_id))
            else:
                 return []
                 
            if not session_data: return []
            
            filenames = []
            for msg in session_data.get("conversation", []):
                if msg.get("role") == "user" and msg.get("audio_path"):
                    # Extract just the filename from the stored path
                    # e.g., "data/.../candidate_turn_1.wav" -> "candidate_turn_1.wav"
                    fname = Path(msg["audio_path"]).name
                    filenames.append(fname)
            
            # Deduplicate and limit
            filenames = sorted(list(set(filenames)))[:limit]
            
            if not filenames: return []

            # 2. Prepare Temp Directory
            temp_dir = Path("data/temp_voice_analysis") / session_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            local_files = []
            
            # 3. Download from GridFS
            for fname in filenames:
                # audio_bytes = self.db.get_file(fname)
                if hasattr(self.db, 'get_file'):
                     if loop.is_running():
                         future = asyncio.run_coroutine_threadsafe(self.db.get_file(fname), loop)
                         audio_bytes = future.result()
                     else:
                         audio_bytes = loop.run_until_complete(self.db.get_file(fname))
                else:
                    logger.warning("DB handler has no get_file method")
                    audio_bytes = None

                if audio_bytes:
                    local_path = temp_dir / fname
                    with open(local_path, "wb") as f:
                        f.write(audio_bytes)
                    local_files.append(local_path)
                else:
                    logger.warning(f"Audio file listed in transcript but missing in GridFS: {fname}")
            
            return local_files

        except Exception as e:
            logger.error(f"Failed to fetch audio from DB: {e}")
            return []

    def _save_voice_reports(self, user_id: str, session_id: str, result: Dict[str, Any]):
        """Saves voice detection reports locally (and optionally to DB if implemented)."""
        try:
            report_dir = self._get_report_directory(user_id, session_id, "final_report")
            
            # Save JSON
            self._save_json_file(result, report_dir / "voice_detection_report.json")
            
            # Save text report
            text_report = self._generate_voice_text_report(result)
            self._save_text_file(text_report, report_dir / "voice_detection_report.txt")
            
        except Exception as e:
            logger.error(f"Failed to save voice reports: {e}")
    
    def _generate_voice_text_report(self, result: Dict[str, Any]) -> str:
        """Generates human-readable text report."""
        lines = []
        lines.append(self._generate_section_header("VOICE FORENSICS & AUTHENTICITY REPORT"))
        
        lines.append(f"User ID: {result['user_id']}\n")
        lines.append(f"Session ID: {result['session_id']}\n")
        
        detection = result.get("detection_result", {})
        integrity = detection.get("integrity_analysis", {})
        
        # 1. Integrity Alerts
        if integrity.get("playback_detected") or integrity.get("whisper_detected"):
            lines.append(self._generate_section_header("!!! INTEGRITY ALERTS !!!", char="!"))
            if integrity.get("playback_detected"):
                lines.append(f"[ALERT] REPLAY ATTACK SUSPECTED (Conf: {integrity.get('playback_confidence')}/10)\n")
                lines.append(f"Evidence: {', '.join(integrity.get('playback_evidence', []))}\n")
            
            if integrity.get("whisper_detected"):
                lines.append(f"[ALERT] EXTERNAL ASSISTANCE / WHISPERING (Conf: {integrity.get('whisper_confidence')}/10)\n")
                lines.append(f"Segments: {', '.join(integrity.get('whisper_segments', []))}\n")
            lines.append("\n")
        
        detection = result.get("detection_result", {})
        
        if detection:
            # Overall Assessment
            lines.append(self._generate_section_header("OVERALL ASSESSMENT", char="-"))
            assessment = detection.get("overall_assessment", {})
            lines.append(f"Verdict: {assessment.get('verdict', 'N/A').upper()}\n")
            lines.append(f"Confidence: {assessment.get('confidence_percentage', 0)}%\n")
            lines.append(f"Risk Level: {assessment.get('risk_level', 'N/A').upper()}\n")
            lines.append(f"Recommendation: {assessment.get('recommendation', 'N/A').upper()}\n\n")
            
            # Voice Authenticity
            lines.append(self._generate_section_header("VOICE AUTHENTICITY", char="-"))
            auth = detection.get("voice_authenticity", {})
            is_human = " YES" if auth.get("is_human") else " NO"
            lines.append(f"Is Human Voice: {is_human}\n")
            lines.append(f"Confidence Score: {auth.get('confidence_score', 0)}/10\n")
            lines.append(f"Classification: {auth.get('classification', 'N/A').upper()}\n\n")
            
            # Detailed Observations
            lines.append(self._generate_section_header("DETAILED OBSERVATIONS", char="-"))
            lines.append(detection.get("detailed_observations", "N/A"))
            lines.append("\n\n")
        
        lines.append(self._generate_section_header("END OF REPORT"))
        
        return "".join(lines)
    
    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
    
    # Required abstract methods
    def analyze(self, *args, **kwargs):
        """Use analyze_voice_authenticity instead."""
        raise NotImplementedError("Use analyze_voice_authenticity")
    
    def _create_prompt(self, *args, **kwargs):
        """Handled by PromptTemplates."""
        raise NotImplementedError("Use PromptTemplates")
