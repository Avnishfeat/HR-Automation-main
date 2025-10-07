# File: app/agents/question_generator/service.py

import json
from typing import List, Any
from app.services.llm_service import LLMService

class QuestionGenerationService:
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    async def generate_questionnaire(self, jd_text: str, requirements: List[str], resume_file: Any) -> List[str]:
        """
        Generates a questionnaire using a text prompt and an uploaded file reference.
        """
        requirements_str = "\n".join(f"- {item}" for item in requirements)
        
        prompt = f"""
        *Important: Do not include any introductory phrases, conversational text, or markdown formatting like ```json.
        Your output must be a raw JSON string that adheres strictly to the specified schema.*
        
        **Role**: You are an expert AI hiring assistant, your questions framing should be more humane and not machine generated.
        **Context**: Your task is to generate a pre-screening questionnaire by analyzing the attached resume file and comparing it against the provided job description and requirements.

        **Input Data**:
        <job_description>{jd_text}</job_description>
        <job_requirements>{requirements_str}</job_requirements>

        **Instructions**:
        1.  Thoroughly analyze the content of the attached resume file.
        2.  Compare the candidate's experience, skills, and education from the file against the job description and requirements.
        3.  Generate exactly 10 questions that probe their qualifications and identify any potential gaps.

        **Output Format**:
        You MUST provide the output as a single, valid JSON array of strings.
        """
        
        # Pass the prompt and the file object to the LLM service
        response_text = await self.llm_service.generate_text(prompt, files=[resume_file])
        
        cleaned_response = response_text.strip().replace("```json", "").replace("```", "").strip()
        try:
            questions = json.loads(cleaned_response)
            return questions
        except json.JSONDecodeError:
            print(f"❌ Error: Failed to decode JSON from LLM response:\n{cleaned_response}")
            raise ValueError("The LLM returned an invalid format.")