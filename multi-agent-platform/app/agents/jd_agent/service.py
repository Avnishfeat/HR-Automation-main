# app/agents/jd_agent/service.py

import os
import logging
from fastapi import HTTPException

# The service no longer needs to import the llm_service directly.
# It will be passed in as an argument by the router.
from app.services.llm_service import LLMService

# Import the schema and role map as before
from .schema import JDInput, ROLE_FILE_MAP

# --- Basic Setup ---
logger = logging.getLogger("jd_agent")

# This helper function does not perform I/O, so it can remain synchronous
def _load_jd_template(job_role: str) -> str:
    """Loads a JD template file based on the job role."""
    base_dir = os.path.dirname(__file__)
    prompts_dir = os.path.join(base_dir, "prompts")
    filename = ROLE_FILE_MAP.get(job_role)

    if not filename:
        raise HTTPException(status_code=400, detail=f"Job role '{job_role}' not available.")

    filepath = os.path.join(prompts_dir, filename)
    if not os.path.exists(filepath):
        logger.error(f"Template file not found at: {filepath}")
        raise HTTPException(status_code=500, detail=f"Template file missing for role: {job_role}")

    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

# The main function is now async and accepts the llm_service instance
async def generate_job_description(payload: JDInput, llm_service: LLMService) -> str:
    """
    Asynchronously generates a job description by using the central LLM service.
    """
    try:
        template = _load_jd_template(payload.job_role)
        user_input_snippet = payload.as_prompt_snippet()
# giving prompt for llm
        prompt = f"""
You are a professional HR assistant. Your task is to generate a detailed and structured Job Description.
Use the provided template and fill in the details based on the user's input.

*Important: Do not include any introductory phrases, conversational text, or code block formatting. Start the output directly with the job description.*


**Job Role:** {payload.job_role}
**Template:**
---
{template}
---
**User Input:**
{user_input_snippet}
"""
        # We 'await' the result from the now-async llm_service method
        generated_text = await llm_service.generate_text(prompt)
        return generated_text
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"An unexpected error occurred in the JD agent: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred in the JD agent.")