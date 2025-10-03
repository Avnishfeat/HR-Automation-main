import os
import logging
import json
from typing import Dict, Any
from fastapi import HTTPException

# The service no longer needs to import the llm_service directly.
# It will be passed in as an argument by the router.
from app.services.llm_service import LLMService

# Import the schema and role map as before
from .schema import JDInput, ROLE_FILE_MAP

# --- Basic Setup ---
logger = logging.getLogger("jd_agent")


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


def _parse_llm_output_to_json(llm_output: str) -> Dict[str, Any]:
    """
    Parses the string output from the LLM into a JSON object.
    Handles potential formatting issues like markdown code blocks.
    """
    try:
        # The LLM might wrap the JSON in a markdown code block (```json ... ```).
        # We need to strip that before parsing.
        if llm_output.strip().startswith("```json"):
            cleaned_output = llm_output.strip()[7:-3].strip()
        elif llm_output.strip().startswith("```"):
            cleaned_output = llm_output.strip()[3:-3].strip()
        else:
            cleaned_output = llm_output

        # Attempt to parse the cleaned string as JSON
        return json.loads(cleaned_output)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM output into JSON. Error: {e}")
        logger.error(f"Raw LLM output was: {llm_output}")
        raise HTTPException(
            status_code=500,
            detail="The model returned an invalid format. Could not parse the job description.",
        )


async def generate_job_description(payload: JDInput, llm_service: LLMService) -> Dict[str, Any]:
    """
    Asynchronously generates a job description and returns it as a JSON object.
    """
    try:
        template = _load_jd_template(payload.job_role)
        user_input_snippet = payload.as_prompt_snippet()

        prompt = f"""
You are a professional HR assistant. Your task is to generate a detailed and structured Job Description.
Use the provided template and fill in the details based on the user's input.

*Important: Do not include any introductory phrases, conversational text, or markdown formatting like ```json.
Your output must be a raw JSON string that adheres strictly to the specified schema.*


**Job Role:** {payload.job_role}

**Template for reference:**
---
{template}
---

**User Input:**
{user_input_snippet}
---

FOLLOW THIS RESPONSE JSON STRUCTURE ALWAYS. OUTPUT ONLY THE JSON OBJECT.
{{
  "required_skills": "string",
  "preferred_skills": "string",
  "minimum_qualification": "string",
  "languages": "string",
  "overview": "string",
  "key_responsibilities": "string",
  "key_skills_and_qualifications": "string",
  "desired_attributes": "string",
  "benefits": "string"
}}
"""
        # We 'await' the result from the now-async llm_service method
        generated_text = await llm_service.generate_text(prompt)
        
        # Parse the generated text to ensure it's valid JSON
        parsed_json = _parse_llm_output_to_json(generated_text)
        
        return parsed_json
        
    except HTTPException as e:
        # Re-raise known HTTP exceptions
        raise e
    except Exception as e:
        logger.error(f"An unexpected error occurred in the JD agent: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred in the JD agent.")