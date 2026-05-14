# app/services/analysis_base.py
"""
Base class for all analysis services.
Provides shared functionality for Gemini API interaction, JSON parsing, and error handling.
"""

import logging
import json
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Custom exception for analysis errors."""
    def __init__(self, analyzer_name: str, error_type: str, message: str, details: Optional[Dict] = None):
        self.analyzer_name = analyzer_name
        self.error_type = error_type
        self.message = message
        self.details = details or {}
        super().__init__(f"[{analyzer_name}] {error_type}: {message}")


class BaseAnalyzer(ABC):
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
        self.model_name = self._normalize_model_name(model_name)
        
        try:
            # Use centralized secrets manager
            from app.agents.interview.config.secrets import secrets
            api_key = secrets.get_required("GEMINI_API_KEY")
            
            self.client = genai.Client(api_key=api_key)
            
            # Generation config
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
            
            logger.info(f"{self.__class__.__name__} initialized with {self.model_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize {self.__class__.__name__}: {e}")
            raise AnalysisError(
                self.__class__.__name__,
                "initialization_failed",
                str(e)
            )

    @staticmethod
    def _normalize_model_name(model_name: str) -> str:
        legacy_models = {
            "gemini-2.0-flash-lite": "gemini-2.5-flash",
            "models/gemini-2.0-flash-lite": "gemini-2.5-flash",
        }
        normalized = legacy_models.get(model_name, model_name)
        if normalized != model_name:
            logger.warning("Replacing unavailable Gemini model %s with %s", model_name, normalized)
        return normalized
    
    # =========================================================================
    # ABSTRACT METHODS (Must be implemented by subclasses)
    # =========================================================================
    
    @abstractmethod
    def analyze(self, *args, **kwargs) -> Dict[str, Any]:
        """Main analysis method. Must be implemented by subclasses."""
        pass
    
    @abstractmethod
    def _create_prompt(self, *args, **kwargs) -> str:
        """Creates the analysis prompt. Must be implemented by subclasses."""
        pass
    
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
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=content,
                config=self.generation_config
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
        session_id: str,
        error_msg: str
    ) -> Dict[str, Any]:
        """Creates standardized error result for analysis methods."""
        return {
            "status": "error",
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
        session_id: str,
        subdir: str
    ) -> Path:
        """Gets and creates report directory path."""
        report_dir = Path("data") / session_id / "reports" / subdir
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
        file_paths: List[Path],
        max_files: Optional[int] = None
    ) -> List[Any]:
        """
        Uploads files to Gemini API.
        
        Args:
            file_paths: List of file paths to upload
            max_files: Maximum number of files to upload
            
        Returns:
            List of uploaded file objects
        """
        if max_files:
            file_paths = file_paths[:max_files]
        
        uploaded_files = []
        
        for file_path in file_paths:
            try:
                # --- FIX: use 'file' argument instead of 'path' ---
                uploaded_file = self.client.files.upload(file=str(file_path))
                uploaded_files.append(uploaded_file)
                logger.debug(f"Uploaded: {file_path.name}")
            except Exception as e:
                logger.warning(f"Failed to upload {file_path}: {e}")
        
        return uploaded_files


class ReportGeneratorMixin:
    """Mixin for generating formatted text reports."""
    
    def _format_score_line(
        self,
        label: str,
        score: Any,
        max_score: int = 10,
        note: Optional[str] = None
    ) -> str:
        """Formats a score line with optional note."""
        score_str = f"{score}/{max_score}" if score is not None else "N/A"
        line = f"{label}: {score_str}"
        if note:
            line += f"({note})"
        return line + "\n"
    
    def _format_list_section(
        self,
        title: str,
        items: List[str],
        bullet: str = "•"
    ) -> str:
        """Formats a list section."""
        if not items:
            return f"{title}:\n  (None)\n\n"
        
        lines = [f"{title}:\n"]
        for item in items:
            lines.append(f"{bullet} {item}\n")
        lines.append("\n")
        
        return "".join(lines)
