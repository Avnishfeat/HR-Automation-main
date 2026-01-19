
"""
Base class for all analysis services.
Provides shared functionality for Gemini API interaction, JSON parsing, and error handling.
"""

import logging
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Custom exception for analysis errors."""
    def __init__(self, analyzer_name: str, error_type: str, message: str, details: Optional[Dict] = None):
        self.analyzer_name = analyzer_name
        self.error_type = error_type
        self.message = message
        self.details = details or {}
        super().__init__(f"[{analyzer_name}] {error_type}: {message}")


class BaseAnalyzer:
    def __init__(
        self,
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.1,
        top_k: int = 1,
        safety_level: str = "BLOCK_ONLY_HIGH"
    ):
        """
        Initialize base analyzer with Gemini configuration.
        """
        self.model = None
        self.model_name = model_name
        
        try:
            api_key = settings.GEMINI_API_KEY
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in settings")

            self.client = genai.Client(api_key=api_key)
            
            # Generation config
            # Note: types might be different if SDK version changed, but keeping as is for now.
            try:
                self.generation_config = types.GenerateContentConfig(
                    temperature=temperature,
                    top_k=top_k,
                    top_p=0.95,
                    safety_settings=[
                        types.SafetySetting(
                            category=category,
                            threshold=safety_level
                        ) for category in [
                            "HARM_CATEGORY_HARASSMENT",
                            "HARM_CATEGORY_HATE_SPEECH",
                            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            "HARM_CATEGORY_DANGEROUS_CONTENT"
                        ]
                    ]
                )
            except AttributeError:
                # Fallback for different SDK versions where types might not be directly at genai.types
                # Or just use dict if supported.
                logger.warning("Could not configure safety settings with types.Using default config.")
                self.generation_config = None
            
            logger.info(f"{self.__class__.__name__} initialized with {model_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize {self.__class__.__name__}: {e}")
            raise AnalysisError(
                self.__class__.__name__,
                "initialization_failed",
                str(e)
            )
    
    # =========================================================================
    # ABSTRACT METHODS (Must be implemented by subclasses)
    # =========================================================================
    
    def analyze(self, *args, **kwargs) -> Dict[str, Any]:
        """Main analysis method. Must be implemented by subclasses."""
        raise NotImplementedError
    
    def _create_prompt(self, *args, **kwargs) -> str:
        """Creates the analysis prompt. Must be implemented by subclasses."""
        raise NotImplementedError
    
    # =========================================================================
    # SHARED API INTERACTION
    # =========================================================================
    
    def _call_gemini_api(
        self,
        content: Any,
        expected_format: str = "json"
    ) -> Dict[str, Any]:
        """
        Calls Gemini API and handles response.
        """
        if not self.client:
            return self._create_error_response("Client not initialized")
        
        try:
            logger.debug(f"Calling Gemini API ({self.model_name})...")
            
            # config works?
            kwargs = {}
            if self.generation_config:
                kwargs['config'] = self.generation_config

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=content,
                **kwargs
            )
            
            if not response:
                return self._create_error_response("Empty response from API")
            
            # Extract text safely
            response_text = self._extract_response_text(response)
            
            if not response_text:
                return self._create_error_response(
                    "No text in response",
                    details={
                        "finish_reason": getattr(response.candidates[0], 'finish_reason', None) if response.candidates else None,
                        "prompt_feedback": str(getattr(response, 'prompt_feedback', None))
                    }
                )
            
            logger.info(" Received response from Gemini API")
            
            # Parse based on expected format
            if expected_format == "json":
                parsed_data = self._extract_and_parse_json(response_text)
                if parsed_data:
                    return {
                        "success": True,
                        "data": parsed_data,
                        "raw_response": response_text
                    }
                else:
                    return self._create_error_response(
                        "Failed to parse JSON",
                        details={"raw_response": response_text}
                    )
            else:
                return {
                    "success": True,
                    "data": response_text,
                    "raw_response": response_text
                }
            
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}", exc_info=True)
            return self._create_error_response(str(e))
    
    def _extract_response_text(self, response) -> str:
        """Safely extracts text from Gemini response."""
        try:
            if hasattr(response, 'text') and response.text:
                return response.text

            if not response.candidates:
                logger.warning("No candidates in response")
                return ""
            
            candidate = response.candidates[0]
            
            if not candidate.content.parts:
                logger.warning("No content parts in response")
                return ""
            
            return candidate.content.parts[0].text
            
        except Exception as e:
            logger.error(f"Error extracting response text: {e}")
            return ""
    
    # =========================================================================
    # JSON PARSING UTILITIES
    # =========================================================================
    
    def _extract_and_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extracts and parses JSON from text.
        Handles both code-blocked and raw JSON.
        """
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = text.strip()
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.debug(f"Attempted to parse: {json_str[:200]}...")
            return None
    
    # =========================================================================
    # ERROR HANDLING
    # =========================================================================
    
    def _create_error_response(
        self,
        error_message: str,
        details: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Creates standardized error response."""
        return {
            "success": False,
            "error": error_message,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
    
    def _create_error_result(
        self,
        user_id: str,
        session_id: str,
        error_msg: str
    ) -> Dict[str, Any]:
        """Creates standardized error result for analysis methods."""
        return {
            "status": "error",
            "user_id": user_id,
            "session_id": session_id,
            "error_message": error_msg,
            "analysis_timestamp": datetime.now().isoformat()
        }
    
    # =========================================================================
    # FILE I/O UTILITIES
    # =========================================================================
    
    def _ensure_directory(self, path: Path) -> Path:
        """Ensures directory exists, creates if not."""
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _save_json_file(
        self,
        data: Dict[str, Any],
        file_path: Path,
        indent: int = 2
    ) -> bool:
        """Saves data as JSON file."""
        try:
            self._ensure_directory(file_path.parent)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            logger.debug(f"Saved JSON to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save JSON to {file_path}: {e}")
            return False
    
    def _save_text_file(
        self,
        content: str,
        file_path: Path
    ) -> bool:
        """Saves content as text file."""
        try:
            self._ensure_directory(file_path.parent)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.debug(f"Saved text to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save text to {file_path}: {e}")
            return False
    
    # =========================================================================
    # REPORT GENERATION UTILITIES
    # =========================================================================
    
    def _get_report_directory(
        self,
        user_id: str,
        session_id: str,
        subdir: str
    ) -> Path:
        """Gets and creates report directory path."""
        # Using a relative path 'data' which should be fine for now, or use settings.UPLOAD_DIR
        report_dir = Path("data") / user_id / session_id / subdir
        return self._ensure_directory(report_dir)
    
    def _generate_section_header(
        self,
        title: str,
        width: int = 80,
        char: str = "="
    ) -> str:
        """Generates formatted section header."""
        return f"\n{char * width}\n{title}\n{char * width}\n"
    
    # =========================================================================
    # VALIDATION UTILITIES
    # =========================================================================
    
    def _validate_score(self, score: Any, default: float = 5.0) -> float:
        """Validates and clamps score to 0-10 range."""
        try:
            score_float = float(score)
            return max(0.0, min(10.0, score_float))
        except (TypeError, ValueError):
            logger.warning(f"Invalid score value: {score}, using default {default}")
            return default
    
    def _extract_score_from_text(
        self,
        text: str,
        default: float = 5.0
    ) -> float:
        """Extracts numeric score from text using regex patterns."""
        if not text:
            return default
        
        # Try various score patterns
        patterns = [
            r'(\d+(?:\.\d+)?)\s*[/-]\s*10',  # "8/10" or "8-10"
            r'rating[:\s]*\(?(\d+(?:\.\d+)?)',  # "rating: 8"
            r'score[:\s]*\(?(\d+(?:\.\d+)?)',   # "score: 8"
            r'(\d+(?:\.\d+)?)\s*out\s*10', # "8 out 10"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return self._validate_score(match.group(1))
                except (ValueError, IndexError):
                    continue
        
        return default


class FileUploadMixin:
    """Mixin for analyzers that need to upload files to Gemini."""
    
    def _upload_files_to_gemini(
        self,
        file_paths: Any, # List[Path] but avoiding circular
        max_files: Optional[int] = None
    ) -> Any: # List[Any]
        """
        Uploads files to Gemini API.
        """
        if max_files:
            file_paths = file_paths[:max_files]
        
        uploaded_files = []
        
        for file_path in file_paths:
            try:
                # Assuming self.client exists (mixed in with BaseAnalyzer)
                uploaded_file = self.client.files.upload(file=str(file_path))
                uploaded_files.append(uploaded_file)
                logger.debug(f"Uploaded: {file_path.name}")
            except Exception as e:
                logger.warning(f"Failed to upload {file_path}: {e}")
        
        return uploaded_files
