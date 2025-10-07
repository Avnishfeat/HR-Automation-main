# File: app/services/llm_service.py

import logging
import google.generativeai as genai
from fastapi import HTTPException
from typing import List, Any
import asyncio
import tempfile
import os

logger = logging.getLogger("llm_service")

class LLMService:
    def __init__(self, settings):
        self.model = None
        self.file_api_supported = True
        try:
            api_key = settings.GEMINI_API_KEY
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in settings.")
            genai.configure(api_key=api_key)
            model_name = settings.GENAI_MODEL or "gemini-2.5-flash" # Models like 1.5 support the File API
            self.model = genai.GenerativeModel(model_name)
            logger.info(f"LLMService initialized with model: {model_name}")
        except Exception as e:
            logger.critical(f"Fatal error during LLMService initialization: {e}")

    # <-- NEW METHOD to handle file uploads
    async def upload_file(self, file_bytes: bytes, display_name: str) -> Any:
        """Uploads a file to the Gemini File API."""
        temp_file_path = None
        try:
            # --- THIS SECTION IS MODIFIED ---
            # 1. Create a temporary file and get its path
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                temp_file.write(file_bytes)
                temp_file_path = temp_file.name
            # The 'with' block is now closed, so the file is no longer in use.

            logger.info(f"Uploading file '{display_name}' from path '{temp_file_path}' to File API...")
            
            # 2. Upload the file using its path
            uploaded_file = await asyncio.to_thread(
                genai.upload_file,
                path=temp_file_path,
                display_name=display_name
            )
            
            logger.info(f"Successfully uploaded file: {uploaded_file.name}")
            return uploaded_file
        except Exception as e:
            logger.error(f"File API upload failed for '{display_name}': {e}")
            raise HTTPException(status_code=500, detail="Failed to upload file to AI service.")
        finally:
            # 3. Clean up the temporary file if it was created
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    # <-- MODIFIED to accept an optional file list
    async def generate_text(self, prompt: str, files: List[Any] = None) -> str:
        """Asynchronously generates text, optionally including file references."""
        if not self.model:
            raise HTTPException(status_code=503, detail="LLM service is not available.")
        try:
            contents = [prompt]
            if files:
                contents.extend(files) # Add file objects to the prompt contents
            
            response = await self.model.generate_content_async(contents)
            return response.text.strip()
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise HTTPException(status_code=502, detail=f"An unexpected error occurred with the AI service: {e}")