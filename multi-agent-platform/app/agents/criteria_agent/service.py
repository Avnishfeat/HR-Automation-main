# app/agents/criteria_agent/service.py

import os
import json
import logging
import asyncio
from fastapi import HTTPException

# Import the central LLM Service and the request schema
from app.services.llm_service import LLMService
from .schema import CriteriaRequest

logger = logging.getLogger("criteria_agent")

# --- Template Mapping ---
CRITERIA_FILE_MAP = {
    "linkedin": "linkedin.json",
    "indeed": "indeed.json",
    "naukri": "naukri.json",
}

def _load_criteria_template(platform_name: str) -> dict:
    """Loads a JSON schema template from the templates directory."""
    base_dir = os.path.dirname(__file__)
    templates_dir = os.path.join(base_dir, "templates")
    filename = CRITERIA_FILE_MAP.get(platform_name)
    
    if not filename:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform_name}")
    
    path = os.path.join(templates_dir, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=500, detail=f"Schema file not found for {platform_name}")
    
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _build_prompt(platform_name: str, jd_text: str) -> str:
    """Builds the prompt for the LLM with the JD and target JSON schema."""
    schema = _load_criteria_template(platform_name)
    schema_str = json.dumps(schema, indent=2)
    
    return f"""
Analyze the following Job Description and extract the key candidate search criteria.
Your response MUST be a valid JSON object that strictly adheres to the provided schema.
Do not include any explanations, markdown formatting, or text outside of the JSON object.

**JSON Schema to Follow:**
```json
{schema_str}

Job Description:
{jd_text}
"""

async def _generate_for_single_target(platform_name: str, jd_text: str, llm_service: LLMService) -> dict:
    """Async helper to generate criteria for one platform."""
    prompt = _build_prompt(platform_name, jd_text)
    raw_response = await llm_service.generate_text(prompt)
    try:
        # Reliable logic to clean up markdown fences from the LLM response
        cleaned_response = raw_response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        
        return json.loads(cleaned_response)
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON for {platform_name}. Raw response: {raw_response}")
        return {"error": "Failed to generate valid JSON.", "raw_output": raw_response}
    
async def generate_criteria(payload: CriteriaRequest, llm_service: LLMService) -> dict:
    """
    Generates candidate search criteria by calling the LLM service.
    Processes multiple targets concurrently if 'target' is 'all'.
    """
    targets = list(CRITERIA_FILE_MAP.keys()) if payload.target == "all" else [payload.target]

    # Create a list of async tasks to run in parallel
    tasks = [_generate_for_single_target(target, payload.jd_text, llm_service) for target in targets]
    
    # Run all tasks concurrently and wait for them to complete
    results = await asyncio.gather(*tasks)
    
    # Combine the results into a dictionary
    return dict(zip(targets, results))