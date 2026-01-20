# app/services/analysis/gender_detector.py
"""
Gender detection service for voice mismatch detection.
Uses Gemini vision for snapshot analysis and name heuristics as backup.
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from PIL import Image

from .analysis_base import BaseAnalyzer, FileUploadMixin

logger = logging.getLogger(__name__)

# Common name gender heuristics (extensible)
MALE_NAMES = {
    'aarav', 'aditya', 'akash', 'amit', 'anil', 'arjun', 'ashish', 'deepak', 
    'gaurav', 'harsh', 'jay', 'john', 'karan', 'kumar', 'michael', 'nikhil', 
    'rahul', 'raj', 'rajesh', 'ravi', 'rohit', 'sachin', 'sanjay', 'shiv', 
    'suresh', 'vijay', 'vikas', 'vinay', 'vishal', 'yash'
}

FEMALE_NAMES = {
    'aarti', 'aisha', 'ananya', 'anjali', 'deepika', 'divya', 'geeta', 
    'ishita', 'kavita', 'kritika', 'meera', 'neha', 'pooja', 'priya', 
    'rashmi', 'rekha', 'riya', 'sakshi', 'sangeeta', 'shreya', 'simran', 
    'sneha', 'sonia', 'sunita', 'swati', 'tanvi', 'varsha'
}


class GenderDetector(BaseAnalyzer, FileUploadMixin):
    """
    Detects expected gender from visual appearance and name.
    Used to compare against voice gender for mismatch detection.
    """
    
    def __init__(self):
        super().__init__(
            model_name="gemini-2.0-flash-lite",
            temperature=0.1,
            safety_level="BLOCK_ONLY_HIGH"
        )
    
    def detect_gender_from_snapshot(self, snapshot_path: Path) -> Dict[str, Any]:
        """
        Uses Gemini vision to detect apparent gender from a face in a snapshot.
        
        Returns:
            {
                "detected_gender": "male" | "female" | "uncertain",
                "confidence": float (1-10),
                "source": "visual"
            }
        """
        try:
            if not snapshot_path.exists():
                return self._uncertain_result("visual", "Snapshot not found")
            
            # Load and upload image
            image = Image.open(snapshot_path)
            
            prompt = """
            Analyze this image of a person in a video call.
            
            Task: Determine the apparent biological gender of the PRIMARY person visible in the frame.
            
            Consider:
            - Facial structure and features
            - Clothing and presentation (but don't rely solely on this)
            - Overall appearance
            
            Return ONLY valid JSON (no markdown):
            {
                "detected_gender": "male" | "female" | "uncertain",
                "confidence": float (1-10, where 10 is very confident),
                "reasoning": "brief explanation"
            }
            """
            
            content = [prompt, image]
            response = self._call_gemini_api(content, expected_format="json")
            
            if response["success"] and response["data"]:
                result = response["data"]
                result["source"] = "visual"
                return result
            
            return self._uncertain_result("visual", "Gemini analysis failed")
            
        except Exception as e:
            logger.error(f"Visual gender detection failed: {e}")
            return self._uncertain_result("visual", str(e))
    
    def detect_gender_from_name(self, candidate_name: str) -> Dict[str, Any]:
        """
        Uses name heuristics to infer gender.
        
        Returns:
            {
                "detected_gender": "male" | "female" | "uncertain",
                "confidence": float (1-10),
                "source": "name_heuristic"
            }
        """
        if not candidate_name:
            return self._uncertain_result("name_heuristic", "No name provided")
        
        # Extract first name and normalize
        first_name = candidate_name.split()[0].lower().strip()
        
        if first_name in MALE_NAMES:
            return {
                "detected_gender": "male",
                "confidence": 7.0,
                "source": "name_heuristic",
                "reasoning": f"Name '{first_name}' is commonly male"
            }
        
        if first_name in FEMALE_NAMES:
            return {
                "detected_gender": "female",
                "confidence": 7.0,
                "source": "name_heuristic",
                "reasoning": f"Name '{first_name}' is commonly female"
            }
        
        return self._uncertain_result("name_heuristic", f"Name '{first_name}' is gender-neutral or unknown")
    
    def detect_expected_gender(
        self, 
        candidate_name: str,
        snapshot_dir: Optional[Path] = None
    ) -> Tuple[str, float, str]:
        """
        Combines visual and name-based detection.
        Visual takes priority if available and confident.
        
        Returns:
            (gender, confidence, source)
        """
        visual_result = None
        name_result = None
        
        # 1. Try visual detection first (higher accuracy)
        if snapshot_dir and snapshot_dir.exists():
            snapshots = sorted(snapshot_dir.glob("snap_*.jpg"))[:1]
            if snapshots:
                visual_result = self.detect_gender_from_snapshot(snapshots[0])
                
                # If visual is confident, use it
                if visual_result.get("confidence", 0) >= 6.0 and visual_result.get("detected_gender") != "uncertain":
                    logger.info(f"Gender from visual: {visual_result}")
                    return (
                        visual_result["detected_gender"],
                        visual_result["confidence"],
                        "visual"
                    )
        
        # 2. Fallback to name heuristics
        name_result = self.detect_gender_from_name(candidate_name)
        
        if name_result.get("detected_gender") != "uncertain":
            logger.info(f"Gender from name: {name_result}")
            return (
                name_result["detected_gender"],
                name_result["confidence"],
                "name_heuristic"
            )
        
        # 3. If visual had some result but low confidence, use it
        if visual_result and visual_result.get("detected_gender") != "uncertain":
            return (
                visual_result["detected_gender"],
                visual_result["confidence"],
                "visual_low_conf"
            )
        
        # 4. Unable to determine
        return ("uncertain", 0.0, "none")
    
    def _uncertain_result(self, source: str, reason: str) -> Dict[str, Any]:
        return {
            "detected_gender": "uncertain",
            "confidence": 0.0,
            "source": source,
            "reasoning": reason
        }
    
    # Required abstract methods
    def analyze(self, *args, **kwargs):
        raise NotImplementedError("Use detect_expected_gender")
    
    def _create_prompt(self, *args, **kwargs):
        raise NotImplementedError("Prompts are inline")
