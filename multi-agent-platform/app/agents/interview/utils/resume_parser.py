# app/utils/pdf_parser.py
"""
Resume Parser Utility for Interview Bot
Extracts text content from PDF, DOCX, and TXT resumes
"""
import logging
from typing import Optional
import io

logger = logging.getLogger(__name__)

# Try multiple PDF parsing libraries for better compatibility
try:
    import pypdf
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    logger.warning("pypdf not available")

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available")

#  NEW: Add DOCX support
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("python-docx not available. Install with: pip install python-docx")


class ResumeParser:
    """Handles resume text extraction from multiple formats (PDF, DOCX, TXT)."""
    
    def __init__(self):
        """Initialize resume parser with available libraries."""
        # Check PDF libraries
        if not PYPDF2_AVAILABLE and not PDFPLUMBER_AVAILABLE:
            logger.error(
                "No PDF parsing library available. Install with: "
                "pip install pypdf pdfplumber"
            )
        
        self.pdf_method_priority = []
        if PDFPLUMBER_AVAILABLE:
            self.pdf_method_priority.append('pdfplumber')
        if PYPDF2_AVAILABLE:
            self.pdf_method_priority.append('pypdf2')
        
        available_formats = []
        if self.pdf_method_priority:
            available_formats.append('PDF')
        if DOCX_AVAILABLE:
            available_formats.append('DOCX')
        available_formats.append('TXT')  # Always available
        
        logger.info(f"Resume parser initialized. Supported formats: {', '.join(available_formats)}")
    
    def extract_text_from_pdf(self, pdf_file) -> Optional[str]:
        """
        Extract text from PDF file using available methods.
        
        Args:
            pdf_file: File-like object or bytes from uploaded PDF
            
        Returns:
            Extracted text as string, or None if extraction fails
        """
        # Convert to bytes if needed
        if hasattr(pdf_file, 'read'):
            pdf_bytes = pdf_file.read()
            pdf_file.seek(0)  # Reset file pointer
        else:
            pdf_bytes = pdf_file
        
        # Try each method in priority order
        for method in self.pdf_method_priority:
            try:
                if method == 'pdfplumber':
                    text = self._extract_with_pdfplumber(pdf_bytes)
                elif method == 'pypdf2':
                    text = self._extract_with_pypdf2(pdf_bytes)
                
                if text and len(text.strip()) > 0:
                    logger.info(f"Successfully extracted {len(text)} characters from PDF using {method}")
                    return text.strip()
                else:
                    logger.warning(f"{method} returned empty text, trying next method...")
                    
            except Exception as e:
                logger.warning(f"Failed to extract with {method}: {e}")
                continue

        logger.error("All PDF extraction methods failed")
        return None
    
    def _extract_with_pdfplumber(self, pdf_bytes: bytes) -> str:
        """Extract text using pdfplumber (generally more accurate)."""
        if not PDFPLUMBER_AVAILABLE:
            return None
        
        import pdfplumber
        
        text_parts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                    logger.debug(f"Extracted text from PDF page {page_num}")
        
        return "\n\n".join(text_parts)
    
    def _extract_with_pypdf2(self, pdf_bytes: bytes) -> str:
        """Extract text using pypdf (fallback method)."""
        if not PYPDF2_AVAILABLE:
            return None
        
        import pypdf
        
        text_parts = []
        pdf_reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
                logger.debug(f"Extracted text from PDF page {page_num + 1}")
        
        return "\n\n".join(text_parts)
    
    #  NEW: DOCX extraction method
    def extract_text_from_docx(self, docx_file) -> Optional[str]:
        """
        Extract text from DOCX file.
        
        Args:
            docx_file: File-like object or bytes from uploaded DOCX
            
        Returns:
            Extracted text as string, or None if extraction fails
        """
        if not DOCX_AVAILABLE:
            logger.error("python-docx library not available. Install with: pip install python-docx")
            return None
        
        try:
            # Convert to bytes if needed
            if hasattr(docx_file, 'read'):
                docx_bytes = docx_file.read()
                docx_file.seek(0)  # Reset file pointer
            else:
                docx_bytes = docx_file
            
            # Load the document
            doc = Document(io.BytesIO(docx_bytes))
            text_parts = []
            
            # Extract text from paragraphs
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text.strip())
            
            # Extract text from tables (resumes often have tables)
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        cell_text = cell.text.strip()
                        if cell_text:
                            # Avoid duplicates (cells can appear in multiple contexts)
                            if cell_text not in text_parts:
                                text_parts.append(cell_text)
            
            if not text_parts:
                logger.error("No text could be extracted from DOCX")
                return None
            
            full_text = "\n\n".join(text_parts)
            logger.info(f"Successfully extracted {len(full_text)} characters from DOCX")
            return full_text.strip()
            
        except Exception as e:
            logger.error(f"Failed to extract text from DOCX: {e}", exc_info=True)
            return None
    
    #  NEW: TXT extraction method
    def extract_text_from_txt(self, txt_file) -> Optional[str]:
        """
        Extract text from TXT file.
        
        Args:
            txt_file: File-like object or bytes from uploaded TXT
            
        Returns:
            Extracted text as string, or None if extraction fails
        """
        try:
            # Convert to bytes if needed
            if hasattr(txt_file, 'read'):
                txt_bytes = txt_file.read()
                txt_file.seek(0)  # Reset file pointer
            else:
                txt_bytes = txt_file
            
            # Try UTF-8 first
            try:
                text = txt_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # Fallback to latin-1 if UTF-8 fails
                logger.warning("UTF-8 decode failed, trying latin-1")
                text = txt_bytes.decode('latin-1')
            
            if not text.strip():
                logger.error("TXT file is empty")
                return None
            
            logger.info(f"Successfully extracted {len(text)} characters from TXT")
            return text.strip()
            
        except Exception as e:
            logger.error(f"Failed to extract text from TXT: {e}", exc_info=True)
            return None
    
    def validate_resume_text(self, text: str) -> bool:
        """
        Validates that extracted text looks like a resume.
        
        Args:
            text: Extracted text to validate
            
        Returns:
            True if text appears to be a valid resume
        """
        if not text or len(text.strip()) < 50:
            logger.warning("Extracted text too short to be a valid resume")
            return False
        
        # Check for common resume keywords
        resume_indicators = [
            'experience', 'education', 'skills', 'work', 'employment',
            'university', 'college', 'degree', 'email', 'phone',
            'project', 'achievement', 'responsibility', 'position',
            'name', 'contact', 'summary', 'profile', 'objective'
        ]
        
        text_lower = text.lower()
        matches = sum(1 for keyword in resume_indicators if keyword in text_lower)
        
        if matches >= 2:
            logger.info(f"Resume validation passed ({matches} indicators found)")
            return True
        else:
            logger.warning(f"Resume validation uncertain (only {matches} indicators found)")
            return True  # Still allow but log warning


#  UPDATED: Main convenience function that handles all formats
def parse_resume_pdf(resume_file) -> Optional[str]:
    """
    Convenience function to extract text from resume (PDF/DOCX/TXT).
    
    Args:
        resume_file: Uploaded resume file (can be PDF, DOCX, or TXT)
        
    Returns:
        Extracted text or None
        
    Note: Function name kept as parse_resume_pdf for backward compatibility,
          but now supports multiple formats.
    """
    parser = ResumeParser()
    
    # Try to determine file type from the file object
    filename = getattr(resume_file, 'filename', '').lower() if hasattr(resume_file, 'filename') else ''
    
    text = None
    
    # If we can determine the file type, use the appropriate parser
    if filename.endswith('.pdf'):
        text = parser.extract_text_from_pdf(resume_file)
    elif filename.endswith('.docx'):
        text = parser.extract_text_from_docx(resume_file)
    elif filename.endswith('.txt'):
        text = parser.extract_text_from_txt(resume_file)
    else:
        # Fallback: try PDF first (most common), then DOCX, then TXT
        logger.warning("Could not determine file type from filename, trying all parsers...")
        text = parser.extract_text_from_pdf(resume_file)
        if not text:
            text = parser.extract_text_from_docx(resume_file)
        if not text:
            text = parser.extract_text_from_txt(resume_file)
    
    if text and parser.validate_resume_text(text):
        return text
    
    return None


#  NEW: Alternative function with explicit format parameter
def parse_resume(resume_file, file_format: str = None) -> Optional[str]:
    """
    Parse resume with explicit format specification.
    
    Args:
        resume_file: Uploaded resume file
        file_format: File format ('pdf', 'docx', or 'txt'). Auto-detected if None.
        
    Returns:
        Extracted text or None
    """
    parser = ResumeParser()
    
    # Auto-detect if not specified
    if not file_format:
        filename = getattr(resume_file, 'filename', '').lower() if hasattr(resume_file, 'filename') else ''
        if filename.endswith('.pdf'):
            file_format = 'pdf'
        elif filename.endswith('.docx'):
            file_format = 'docx'
        elif filename.endswith('.txt'):
            file_format = 'txt'
    
    # Parse based on format
    text = None
    if file_format == 'pdf':
        text = parser.extract_text_from_pdf(resume_file)
    elif file_format == 'docx':
        text = parser.extract_text_from_docx(resume_file)
    elif file_format == 'txt':
        text = parser.extract_text_from_txt(resume_file)
    else:
        logger.error(f"Unsupported file format: {file_format}")
        return None
    
    if text and parser.validate_resume_text(text):
        return text
    
    return None