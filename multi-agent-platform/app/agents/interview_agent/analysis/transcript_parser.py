
# app/services/interview/analysis/transcript_parser.py
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class TranscriptParser:
    @staticmethod
    def parse(transcript_content: str) -> Dict[str, Any]:
        if not transcript_content or not transcript_content.strip():
            logger.warning("TranscriptParser: Received empty content")
            return {
                'metadata': {},
                'transcript_text': "",
                'qa_pairs': []
            }
        
        lines = transcript_content.strip().split('\n')
        
        # Extract metadata if available (safe fallback)
        metadata = TranscriptParser._extract_metadata(lines)
        
        return {
            'metadata': metadata,
            'transcript_text': transcript_content,
            'qa_pairs': [] 
        }
    
    @staticmethod
    def _extract_metadata(lines: List[str]) -> Dict[str, str]:
        """Extract session ID and User ID from headers (if present)."""
        metadata = {}
        
        try:
            # Scan first 20 lines for headers
            for line in lines[:20]:
                line_lower = line.lower().strip()
                
                if ':' in line:
                    parts = line.split(':', 1)
                    key = parts[0].strip().lower()
                    val = parts[1].strip()
                    
                    if key == 'session id':
                        metadata['session_id'] = val
                    elif key == 'candidate id':
                        metadata['user_id'] = val
                    elif key == 'date':
                        metadata['date'] = val
                        
        except Exception as e:
            logger.warning(f"Metadata extraction failed (non-critical): {e}")
        
        return metadata
