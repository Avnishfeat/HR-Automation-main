import os
import json
from pydub import AudioSegment
import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse

from .schemas import FinalAnalysisResponse, FairnessMetrics, TokenUsage
from app.core.config import settings


try:
    genai.configure(api_key=settings.GEMINI_API_KEY)
except (KeyError, AttributeError):
    print("FATAL ERROR: GEMINI_API_KEY not found.")


def _get_text_from_gemini_response(response: GenerateContentResponse) -> str:
    if not response.candidates:
        print("Warning: Gemini response was blocked or had no candidates.")
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


def process_final_analysis(
    user_id: str,
    resume_text: str,
    jd_text: str,
    audio_path: str
) -> FinalAnalysisResponse:
    print(f"Starting final analysis for: {audio_path}")
    audio_file = None
    
    try:
        audio_segment = AudioSegment.from_file(audio_path)
        audio_duration_seconds = len(audio_segment) / 1000.0

        audio_file = genai.upload_file(path=audio_path)
        print(f"File uploaded successfully: {audio_file.name}")

        model = genai.GenerativeModel(model_name=settings.GENAI_MODEL)
        
        prompt = f"""
        You are an expert HR Tech Analyst. Analyze the provided audio file of a job interview.
        Your task is to produce three things in a single JSON object:
        1.  A key "full_transcript" with the complete transcript of the conversation, labeling each line with "Interviewer: " or "Interviewee: ".
        2.  A key "interviewer_analysis" with a SINGLE STRING summary (2-3 sentences) analyzing the interviewer's questions based on the JOB DESCRIPTION and RESUME.
        3.  A key "interviewer_sentiment" with a SINGLE WORD classification ("Positive", "Neutral", or "Negative") of the interviewer's overall tone.

        --- JOB DESCRIPTION ---
        {jd_text}
        --- RESUME ---
        {resume_text}
        """

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
        
        interviewer_analysis_str = analysis_data.get("interviewer_analysis", "Analysis could not be generated.")
        interviewer_sentiment_str = analysis_data.get("interviewer_sentiment", "Neutral")

        return FinalAnalysisResponse(
            user_id=user_id,
            interviewer_analysis=interviewer_analysis_str,
            fairness_analysis=FairnessMetrics(interviewer_sentiment=interviewer_sentiment_str),
            token_usage=token_usage,
        )

    except Exception as e:
        print(f"An error occurred during the final analysis: {e}")
        return FinalAnalysisResponse(
            user_id=user_id,
            interviewer_analysis=f"An error occurred: {e}",
            fairness_analysis=FairnessMetrics(interviewer_sentiment="Error"),
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