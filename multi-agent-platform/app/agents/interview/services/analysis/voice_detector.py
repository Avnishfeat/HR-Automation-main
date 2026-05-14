# app/services/analysis/voice_detector.py
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from .analysis_base import BaseAnalyzer, FileUploadMixin

logger = logging.getLogger(__name__)

class VoiceDetector(BaseAnalyzer, FileUploadMixin):
    def __init__(self):
        super().__init__(
            model_name="gemini-2.5-flash",
            temperature=0.1,
            safety_level="BLOCK_ONLY_HIGH"
        )

    def analyze_voice_authenticity(self, session_id: str, max_samples: int = 5) -> Optional[Dict[str, Any]]:
        try:
            audio_dir = Path("data") / session_id / "audio"
            if not audio_dir.exists(): return None

            audio_files = sorted(list(audio_dir.glob("candidate_turn_*_stt_24k.wav")))[:max_samples]
            if not audio_files: return None

            uploaded = self._upload_files_to_gemini(audio_files, max_files=max_samples)
            if not uploaded: return None

            prompt = "Analyze voice authenticity and gender. Return JSON."
            response = self._call_gemini_api([prompt] + uploaded, expected_format="json")

            if not response["success"]: return None

            result = {
                "session_id": session_id,
                "analysis_timestamp": self._get_timestamp(),
                "detection_result": response["data"],
                "status": "success"
            }

            # Save
            path = Path("data") / session_id / "reports" / "voice_detection_report.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(path, "w") as f:
                json.dump(result, f, indent=4)

            return result
        except Exception as e:
            logger.error(f"Voice detection failed: {e}")
            return None

    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
    def analyze(self, *args, **kwargs): pass
    def _create_prompt(self, *args, **kwargs): pass
