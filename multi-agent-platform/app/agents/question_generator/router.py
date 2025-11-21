# File: app/agents/question_generator/router.py

import os
from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import List, Set

# Local Imports
from .service import QuestionGenerationService
from .schema import QuestionnaireResponse, ErrorResponse

# Shared Application Imports
from app.core.dependencies import get_llm_service
from app.services.llm_service import LLMService

router = APIRouter()

# Define allowed content types
ALLOWED_MIMETYPES: Set[str] = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}

def get_question_generation_service(llm_service: LLMService = Depends(get_llm_service)):
    return QuestionGenerationService(llm_service=llm_service)

@router.post(
    "/generate",
    response_model=QuestionnaireResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"}
    }
)
async def generate_questionnaire_from_file_endpoint(
    jd_text: str = Form(..., description="The full text of the job description."),
    requirements: List[str] = Form(..., description="A list of specific job requirements."),
    resume_file: UploadFile = File(..., description="The candidate's resume (PDF, TXT, or DOCX)."),
    qg_service: QuestionGenerationService = Depends(get_question_generation_service),
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Accepts a job description, requirements, and a resume file, uploads the file
    to the Gemini File API, and generates a questionnaire.
    """
    print("🚀 Received new request to generate questionnaire.")

    if resume_file.content_type not in ALLOWED_MIMETYPES:
        print(f"❌ Error: Invalid file type ({resume_file.content_type}). Must be PDF, TXT, or DOCX.")
        return JSONResponse(
            status_code=400,
            content={"status": False, "detail": "Invalid file type. Please upload a PDF, TXT, or DOCX file."}
        )
    try:
        print(f"📄 Reading bytes from resume: {resume_file.filename} (Type: {resume_file.content_type})")
        resume_bytes = await resume_file.read()
        
        print(f"📤 Uploading '{resume_file.filename}' to LLM file service...")
        uploaded_resume_file = await llm_service.upload_file(
            file_bytes=resume_bytes,
            display_name=resume_file.filename
        )
        print("✅ File uploaded successfully.")

        print("🧠 Generating questions based on JD, requirements, and resume...")
        questions = await qg_service.generate_questionnaire(
            jd_text=jd_text,
            requirements=requirements,
            resume_file=uploaded_resume_file
        )
        print(f"✅ Generated {len(questions)} questions successfully.")

        # --- SAVE QUESTIONS TO FILE ---
        try:
            print(f"💾 Attempting to save questions for '{resume_file.filename}'...")
            
            # --- CHANGE APPLIED HERE ---
            # 1. Define common suffixes to remove
            suffixes_to_remove = ['resume', 'cv']
            
            # 2. Get base filename (e.g., "John_Doe_Resume")
            base_filename, _ = os.path.splitext(resume_file.filename)
            
            # 3. Normalize and split (e.g., "John_Doe_Resume" -> ['John', 'Doe', 'Resume'])
            name_parts = base_filename.replace('_', ' ').split()
            
            # 4. Filter out the suffixes (e.g., ['John', 'Doe'])
            clean_parts = [part for part in name_parts if part.lower() not in suffixes_to_remove]
            
            # 5. Join to get the user's name (e.g., "John Doe")
            user_name = " ".join(clean_parts)
            
            # 6. Define the output directory and filename
            output_dir = "saved_questions"
            output_filename = f"{user_name}_questions.txt" # e.g., "John Doe_questions.txt"
            # --- END OF CHANGE ---

            output_path = os.path.join(output_dir, output_filename)
            
            os.makedirs(output_dir, exist_ok=True)
            
            # Write questions with numbering
            with open(output_path, "w", encoding="utf-8") as f:
                for i, q in enumerate(questions, 1): # Start numbering from 1
                    f.write(f"{i}. {q}\n") # Write as "1. Question text"
            
            print(f"✅ Successfully saved questions to {output_path}")

        except Exception as e:
            print(f"⚠️ Warning: Failed to save questions to file. Error: {e}")
        # --- END OF SAVE ---

        print("✅ Successfully processed request. Returning questions to user.")
        return QuestionnaireResponse(status=True, questions=questions)
        
    except ValueError as e:
        print(f"❌ Error (ValueError): {e}")
        return JSONResponse(
            status_code=400,
            content={"status": False, "detail": str(e)}
        )
    except Exception as e:
        print(f"❌ Error (Exception): An unexpected error occurred: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": False, "detail": f"An unexpected error occurred: {e}"}
        )