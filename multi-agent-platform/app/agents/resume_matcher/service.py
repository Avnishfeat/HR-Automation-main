import logging
import json
from typing import Dict, Any
from fastapi import HTTPException
from app.services.llm_service import LLMService

logger = logging.getLogger("resume_matcher")

def _parse_llm_output_to_json(llm_output: str) -> Dict[str, Any]:
    try:
        if llm_output.strip().startswith("```json"):
            cleaned_output = llm_output.strip()[7:-3].strip()
        elif llm_output.strip().startswith("```"):
            cleaned_output = llm_output.strip()[3:-3].strip()
        else:
            cleaned_output = llm_output
        return json.loads(cleaned_output)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM output into JSON. Error: {e}")
        logger.error(f"Raw LLM output was: {llm_output}")
        raise HTTPException(
            status_code=500,
            detail="The model returned an invalid format. Could not parse the match results.",
        )

async def compare_jd_and_resume(jd_text: str, resume_text: str, llm_service: LLMService) -> Dict[str, Any]:
    try:
        prompt = f"""
You are an expert HR recruitment assistant. Your task is to compare a Job Description (JD) and a Candidate's Resume.
You will evaluate how well the candidate's skills and experience match the job requirements, and also extract key candidate details.

**Job Description:**
{jd_text}

**Resume:**
{resume_text}

Provide your evaluation in strict JSON format matching the structure below.
Extract the candidate's name, email, contact number, social links, skills, and a brief experience summary directly from the resume.
Do NOT include any markdown blocks (like ```json), conversational text, or explanations outside the JSON object.

**REQUIRED RESPONSE JSON STRUCTURE:**
{{
  "candidate_name": "John Doe",
  "email": "john.doe@example.com",
  "contact": "+1234567890",
  "socials": ["https://linkedin.com/in/johndoe", "https://github.com/johndoe"],
  "confidence_score": 0.85,
  "skills": ["Python", "AWS", "Machine Learning"],
  "experience": "5 years of experience in software development and 2 years in machine learning.",
  "strengths": [
    "Strong background in Machine Learning.",
    "5 years of software development experience."
  ],
  "weaknesses": [
    "Candidate lacks 3 years of experience in Python as required.",
    "No mention of cloud certification (AWS/Azure) in the resume."
  ]
}}
"""
        generated_text = await llm_service.generate_text(prompt)
        parsed_json = _parse_llm_output_to_json(generated_text)

        # Basic validation
        if "confidence_score" not in parsed_json or "strengths" not in parsed_json or "weaknesses" not in parsed_json:
            raise ValueError("LLM response missing required fields.")

        return parsed_json
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error comparing JD and resume: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred while comparing JD and Resume.")
