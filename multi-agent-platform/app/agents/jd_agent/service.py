import logging
import json
from typing import Dict, Any
from fastapi import HTTPException

# The service no longer needs to import the llm_service directly.
# It will be passed in as an argument by the router.
from app.services.llm_service import LLMService

# Import the schema
from .schema import JDInput

# --- Basic Setup ---
logger = logging.getLogger("jd_agent")


def _parse_llm_output_to_json(llm_output: str) -> Dict[str, Any]:
    """
    Parses the string output from the LLM into a JSON object.
    Handles potential formatting issues like markdown code blocks.
    """
    try:
        # The LLM might wrap the JSON in a markdown code block (```json ... ```).
        # We need to strip that before parsing.
        cleaned_output = llm_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[7:-3].strip()
        elif cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[3:-3].strip()

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
    Uses a single generalized prompt for any job role.
    """
    try:
        user_input_snippet = payload.as_prompt_snippet()

        prompt = f"""
You are a professional HR assistant. Your task is to generate a detailed and structured Job Description based on the user's input.

**STEP 1: VALIDATION**
First, evaluate the "Job Title" provided: "{payload.job_role}".
Is this a legitimate, recognizable job position or role in any professional industry? 
- If the input is nonsense, gibberish, a person's name, a place, or otherwise clearly not a job role, you must return an error.
- If it is a valid job role, proceed to Step 2.

**STEP 2: GENERATION**
Generate a complete, professional job description using the details provided below.

**Instructions for Missing Values:**
- Use the provided user input to fill the fields.
- If a value is NOT provided in the User Input and cannot be confidently inferred from the Role, set the value to `null`.
- Do not make up fake data for `salary_range`, `work_location`, `experience_range` if not provided.
- **IMPORTANT**: For `preferred_skills`, `overview`, `key_responsibilities`, `benefits`, `desired_attributes`, and `key_skills_and_qualifications`, if the user has not provided enough detail, YOU MUST GENERATE professional, relevant content based on the `job_role` and `requirements`.

**User Input Details:**
---
{user_input_snippet}
---

**REQUIRED RESPONSE FORMAT:**
Your output must be a single, valid JSON object ONLY. Do not include any markdown formatting, code blocks, or introductory text.

If the job role is INVALID, return:
{{
  "error": "Invalid job position: '{payload.job_role}'. Please provide a legitimate job title."
}}

If the job role is VALID, return:
{{
  "requester_recruiter_details": {{
      "employee_id": "string or null",
      "employee_name": "string or null",
      "employee_email_id": "string or null",
      "reports_to_id": "string or null",
      "reports_to_name": "string or null",
      "reports_to_email": "string or null"
  }},
  "basic_job_details": {{
      "job_code": "string or null",
      "job_title": "{payload.job_role}",
      "no_of_positions": "string or null",
      "oprations": "INSERT",
      "department": "string or null",
      "job_type": "string or null",
      "work_location": "string or null",
      "jd_shift": "string or null",
      "total_budget": "string or null",
      "postion_open_date": "string or null",
      "positionclosedate": "string or null",
      "jd_validity_period": "string or null",
      "experience_range": "string or null",
      "salary_range": "string or null",
      "joining_timeline": "string or null",
      "travel_requirement": "string or null"
  }},
  "role_description": {{
      "required_skills": "string",
      "preferred_skills": "string",
      "minimum_qualifications": "string",
      "languages": "string",
      "overview": "string",
      "key_responsibilities": "string",
      "benefits": "string",
      "desired_attributes": "string",
      "key_skills_and_qualifications": "string"
  }}
}}
"""
        # Generate content using the LLM
        generated_text = await llm_service.generate_text(prompt)
        
        # Parse the generated text to ensure it's valid JSON
        parsed_json = _parse_llm_output_to_json(generated_text)
        
        # Check for validation error returned by the LLM
        if "error" in parsed_json:
            raise HTTPException(status_code=400, detail=parsed_json["error"])
        
        return parsed_json
        
    except HTTPException as e:
        # Re-raise known HTTP exceptions
        raise e
    except Exception as e:
        logger.error(f"An unexpected error occurred in the JD agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred in the JD agent: {str(e)}")