from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional
import shutil
import fitz

from . import schemas, service
from app.core.config import settings

router = APIRouter()

@router.post("/hr-analysis-interview", response_model=schemas.HRAnalysisResponse)
def analyze_hr_interview_endpoint(
    userid: str = Form(...),
    resume_text: str = Form(...),
    job_description_text: str = Form(...),
    audio_file: UploadFile = File(...),
    company_guidelines_file: Optional[UploadFile] = File(None)
):
    guidelines_text = None
    
    if company_guidelines_file and company_guidelines_file.size > 0:
        try:
            if company_guidelines_file.content_type == "application/pdf":
                pdf_document = fitz.open(
                    stream=company_guidelines_file.file.read(), 
                    filetype="pdf"
                )
                guidelines_text = ""
                for page in pdf_document:
                    guidelines_text += page.get_text()
                pdf_document.close()
                
            elif company_guidelines_file.content_type == "text/plain":
                guidelines_text = company_guidelines_file.file.read().decode("utf-8")
                
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported file type for company guidelines. Please upload a .txt or .pdf file."
                )

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not read company guidelines file: {e}"
            )
            
        finally:
            company_guidelines_file.file.close()

    temp_audio_path = settings.TEMP_DIR / audio_file.filename
    
    try:
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)

        analysis_result = service.process_hr_interview_analysis(
            user_id=userid,
            resume_text=resume_text,
            jd_text=job_description_text,
            audio_path=str(temp_audio_path),
            guidelines_text=guidelines_text
        )
        
        return analysis_result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An internal error occurred: {e}"
        )
        
    finally:
        audio_file.file.close()