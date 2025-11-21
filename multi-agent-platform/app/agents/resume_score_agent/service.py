import os
import io
import json
import logging
from pathlib import Path
from fastapi import HTTPException, UploadFile
from typing import Dict, Any

from .schema import AnalysisResponse
from app.services.llm_service import LLMService

logger = logging.getLogger("resume_agent")

# Define the set of allowed file extensions
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _load_prompt_template() -> str:
    """
    Load the prompt template from the prompts/analysis_prompt.txt file.
    The path is constructed relative to this service.py file.
    
    File location: app/agents/resume_agent/prompts/analysis_prompt.txt
    """
    try:
        # Get the directory where this service.py file is located
        # This will be: app/agents/resume_agent/
        current_dir = Path(__file__).parent
        
        # Construct path to the prompts directory
        prompts_dir = current_dir / "prompts"
        prompt_file_path = prompts_dir / "analysis_prompt.txt"
        
        logger.info(f"Loading prompt template from: {prompt_file_path}")
        
        # Check if file exists
        if not prompt_file_path.exists():
            raise FileNotFoundError(
                f"Prompt template not found at: {prompt_file_path}. "
                f"Please ensure the file exists at app/agents/resume_agent/prompts/analysis_prompt.txt"
            )
        
        # Read and return the prompt content
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        logger.info(f"Successfully loaded prompt template ({len(content)} characters)")
        return content
            
    except FileNotFoundError as e:
        logger.error(f"Prompt template file not found: {e}")
        raise HTTPException(
            status_code=500,
            detail="Prompt template file not found. Please ensure prompts/analysis_prompt.txt exists in the resume_agent directory."
        )
    except Exception as e:
        logger.error(f"Error loading prompt template: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading prompt template: {str(e)}"
        )


def _parse_llm_output_to_json(llm_output: str) -> Dict[str, Any]:
    """
    Parses the string output from the LLM into a JSON object.
    Handles potential formatting issues like markdown code blocks.
    """
    try:
        # The LLM might wrap the JSON in a markdown code block
        cleaned_output = llm_output.strip()
        
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[7:]
        elif cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[3:]
        
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-3]
        
        cleaned_output = cleaned_output.strip()
        
        # Attempt to parse the cleaned string as JSON
        return json.loads(cleaned_output)
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM output into JSON. Error: {e}")
        logger.error(f"Raw LLM output was: {llm_output}")
        raise HTTPException(
            status_code=500,
            detail="The model returned an invalid format. Could not parse the analysis results."
        )


async def analyze_resume(
    job_description: str, 
    resume_file: UploadFile,
    llm_service: LLMService
) -> AnalysisResponse:
    """
    Analyzes the resume against the job description using the LLM service.
    
    Args:
        job_description: The job description text
        resume_file: The uploaded resume file
        llm_service: The LLM service instance (injected)
    
    Returns:
        AnalysisResponse with the analysis results
    """
    
    # File Type Validation
    file_name, file_extension = os.path.splitext(resume_file.filename)
    file_extension = file_extension.lower()
    
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unacceptable file type: '{file_extension}'. Only .pdf, .docx, and .txt files are allowed."
        )

    try:
        # 1. Read the file bytes
        logger.info(f"Reading file: {resume_file.filename}")
        resume_file_bytes = await resume_file.read()
        
        if not resume_file_bytes:
            raise HTTPException(status_code=400, detail="The resume file is empty.")

        # 2. Upload file to Gemini using the LLM service
        logger.info(f"Uploading {len(resume_file_bytes)} bytes to LLM service...")
        
        uploaded_file = await llm_service.upload_file(
            file_bytes=resume_file_bytes,
            display_name=resume_file.filename
        )
        
        logger.info(f"File uploaded successfully")

        # 3. Load the prompt template
        prompt_template = _load_prompt_template()
        prompt = prompt_template.format(job_description=job_description)

        # 4. Generate analysis using LLM service with the uploaded file
        logger.info("Generating analysis...")
        
        # Pass the file to the LLM service
        response_text = await llm_service.generate_text(
            prompt=prompt,
            files=[uploaded_file]
        )
        
        # 5. Parse and validate the response
        analysis_data = _parse_llm_output_to_json(response_text)
        validated_response = AnalysisResponse(**analysis_data)
        
        logger.info("Analysis completed successfully")
        return validated_response

    except HTTPException:
        # Re-raise known HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error during analysis: {type(e).__name__}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred during resume analysis: {str(e)}"
        )