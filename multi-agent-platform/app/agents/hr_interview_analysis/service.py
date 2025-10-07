import os
import json
from pydub import AudioSegment
from typing import Optional
import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse

from .schemas import HRAnalysisResponse, TokenUsage
from app.core.config import settings


try:
    genai.configure(api_key=settings.GEMINI_API_KEY)
except (KeyError, AttributeError):
    print("FATAL ERROR: GEMINI_API_KEY not found.")


def _get_text_from_gemini_response(response: GenerateContentResponse) -> str:
    if not response.candidates:
        return ""
    
    try:
        if isinstance(response.text, str):
            return response.text
    except (AttributeError, ValueError):
        pass
    
    try:
        if response.parts:
            return "".join(part.text for part in response.parts)
    except Exception as e:
        print(f"Warning: Could not process response.parts. Error: {e}")
    
    print(f"Warning: Encountered an unexpected Gemini response structure. Type: {type(response)}")
    return ""


def process_hr_interview_analysis(
    user_id: str,
    resume_text: str,
    jd_text: str,
    audio_path: str,
    guidelines_text: Optional[str] = None
) -> HRAnalysisResponse:
    print(f"Starting HR interview analysis for: {audio_path}")
    audio_file = None
    
    try:
        audio_segment = AudioSegment.from_file(audio_path)
        audio_duration_seconds = len(audio_segment) / 1000.0

        audio_file = genai.upload_file(path=audio_path)
        print(f"File uploaded successfully: {audio_file.name}")

        model = genai.GenerativeModel(model_name=settings.GENAI_MODEL)
        
        prompt_base = f"""
        You are an expert HR Analyst. Your task is to analyze the provided audio file of an HR interview round, focusing exclusively on the HR interviewer's performance.
        Based on the audio, the candidate's RESUME, and the JOB DESCRIPTION, provide a detailed analysis.

        Return your analysis as a single, valid JSON object.
        """

        json_keys = [
            '"interviewer_relevance_analysis": A string summary (2-3 sentences) evaluating if the interviewer\'s questions were relevant to the job description and the candidate\'s resume.',
            '"interviewer_sentiment": A single-word classification of the interviewer\'s overall tone ("Positive", "Neutral", or "Negative").'
        ]

        if guidelines_text:
            json_keys.append('"company_guidelines_analysis": A string summary (2-3 sentences) evaluating how well the interviewer explained the company policies compared to the provided COMPANY GUIDELINES.')
            prompt_guidelines = f"\n\n--- COMPANY GUIDELINES ---\n{guidelines_text}"
        else:
            prompt_guidelines = ""

        prompt = f"{prompt_base}\nThe JSON object must contain the following keys:\n{', '.join(json_keys)}\n\n--- JOB DESCRIPTION ---\n{jd_text}\n\n--- RESUME ---\n{resume_text}{prompt_guidelines}"

        response = model.generate_content([audio_file, prompt])
        usage = response.usage_metadata
        token_usage = TokenUsage(
            prompt_tokens=usage.prompt_token_count,
            response_tokens=usage.candidates_token_count,
            total_tokens=usage.total_token_count,
            audio_seconds=round(audio_duration_seconds, 2)
        )

        raw_response_text = _get_text_from_gemini_response(response)
        if not raw_response_text:
            raise ValueError("Received an empty response from the Gemini API.")

        cleaned_json = raw_response_text.strip().lstrip("```json").rstrip("```")
        analysis_data = json.loads(cleaned_json)
        
        return HRAnalysisResponse(
            user_id=user_id,
            interviewer_relevance_analysis=analysis_data.get("interviewer_relevance_analysis", "Analysis not available."),
            company_guidelines_analysis=analysis_data.get("company_guidelines_analysis"),
            interviewer_sentiment=analysis_data.get("interviewer_sentiment", "Neutral"),
            token_usage=token_usage,
        )

    except Exception as e:
        print(f"An error occurred during the HR analysis: {e}")
        return HRAnalysisResponse(
            user_id=user_id,
            interviewer_relevance_analysis=f"An error occurred: {e}",
            company_guidelines_analysis="An error occurred during analysis.",
            interviewer_sentiment="Error",
            token_usage=TokenUsage(
                prompt_tokens=0,
                response_tokens=0,
                total_tokens=0,
                audio_seconds=0
            )
        )
        
    finally:
        if audio_file:
            print(f"Deleting uploaded file from Gemini storage: {audio_file.name}")
            genai.delete_file(audio_file.name)
        if os.path.exists(audio_path):
            os.remove(audio_path)