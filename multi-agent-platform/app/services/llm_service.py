# app/services/llm_service.py

import logging
import google.generativeai as genai
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("llm_service")

class LLMService:
    """
    A centralized service to handle all interactions with the Large Language Model (LLM).
    """
    def __init__(self, settings):
        self.model = None
        try:
            # Get the API key from the settings object, based on your preference
            api_key = settings.GEMINI_API_KEY
            if not api_key:
                # Corrected the error message to be consistent
                raise ValueError("GEMINI_API_KEY not found in settings.")
            
            genai.configure(api_key=api_key)
            
            # Get the model name from settings, with a fallback default.
            model_name = settings.GENAI_MODEL or "gemini-2.5-flash"
            self.model = genai.GenerativeModel(model_name)
            logger.info(f"LLMService initialized successfully with model: {model_name}")

        except Exception as e:
            logger.critical(f"Fatal error during LLMService initialization: {e}")
            # If the service can't start, self.model will remain None

    # This method is now async to avoid blocking the server
    async def generate_text(self, prompt: str) -> str:
        """
        Asynchronously generates text using the configured LLM.
        """
        if not self.model:
            raise HTTPException(status_code=503, detail="LLM service is not configured or available.")
        
        try:
            # Run the synchronous, blocking SDK call in a separate thread
            response = await run_in_threadpool(self.model.generate_content, prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise HTTPException(status_code=502, detail=f"An unexpected error occurred with the AI service: {e}")

# NOTE: The singleton instance of this class should be created in your dependencies.py file.