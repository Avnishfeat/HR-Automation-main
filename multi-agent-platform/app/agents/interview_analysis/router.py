from fastapi import APIRouter, UploadFile, File, Form, HTTPException
import shutil

from . import schemas, service
from app.core.config import settings

router = APIRouter()


@router.post("/analysis-interview", response_model=schemas.FinalAnalysisResponse)
def analyze_interview_endpoint(
    userid: str = Form(...),
    resume_text: str = Form(...),
    job_description_text: str = Form(...),
    audio_file: UploadFile = File(...)
):
    temp_audio_path = settings.TEMP_DIR / audio_file.filename
    
    try:
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)

        analysis_result = service.process_final_analysis(
            user_id=userid,
            resume_text=resume_text,
            jd_text=job_description_text,
            audio_path=str(temp_audio_path)
        )
        
        return analysis_result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An internal error occurred: {e}"
        )
        
    finally:
        audio_file.file.close()