# File: tests/agents/question_generator/test_service.py

import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from app.services.llm_service import LLMService
from app.agents.question_generator.service import QuestionGenerationService

@pytest.fixture
def mock_llm_service():
    """Fixture for a mock LLMService."""
    return MagicMock(spec=LLMService)

@pytest.fixture
def qg_service(mock_llm_service: MagicMock):
    """Fixture for the QuestionGenerationService injected with the mock."""
    return QuestionGenerationService(llm_service=mock_llm_service)

@pytest.mark.asyncio
class TestQuestionGenerationService:

    async def test_generate_questionnaire_success(self, qg_service: QuestionGenerationService, mock_llm_service: MagicMock):
        """Tests the happy path where the LLM returns valid JSON."""
        # Arrange
        expected_questions = ["Question 1?", "Question 2?", "Question 12?"]
        mock_response = json.dumps(expected_questions)
        mock_llm_service.generate_text = AsyncMock(return_value=mock_response)
        
        jd = "Senior Python Developer"
        reqs = ["FastAPI", "Asyncio"]
        mock_file = MagicMock(name="UploadedFile")

        # Act
        questions = await qg_service.generate_questionnaire(
            jd_text=jd,
            requirements=reqs,
            resume_file=mock_file
        )

        # Assert
        assert questions == expected_questions
        
        # Check that the LLM was called correctly
        mock_llm_service.generate_text.assert_called_once()
        call_args = mock_llm_service.generate_text.call_args
        prompt = call_args[0][0] # First positional arg is the prompt
        files = call_args[1]['files'] # Keyword arg 'files'

        assert "<job_description>Senior Python Developer</job_description>" in prompt
        assert "- FastAPI\n- Asyncio" in prompt
        assert files == [mock_file]

    async def test_generate_questionnaire_cleans_markdown(self, qg_service: QuestionGenerationService, mock_llm_service: MagicMock):
        """Tests that the service strips ```json markdown wrappers."""
        # Arrange
        expected_questions = ["Cleaned Q1"]
        mock_response = f"```json\n{json.dumps(expected_questions)}\n```"
        mock_llm_service.generate_text = AsyncMock(return_value=mock_response)

        # Act
        questions = await qg_service.generate_questionnaire("jd", ["req"], MagicMock())

        # Assert
        assert questions == expected_questions

    async def test_generate_questionnaire_cleans_whitespace(self, qg_service: QuestionGenerationService, mock_llm_service: MagicMock):
        """Tests that the service strips leading/trailing whitespace."""
        # Arrange
        expected_questions = ["Trimmed Q1"]
        mock_response = f"  \n{json.dumps(expected_questions)} \n "
        mock_llm_service.generate_text = AsyncMock(return_value=mock_response)

        # Act
        questions = await qg_service.generate_questionnaire("jd", ["req"], MagicMock())

        # Assert
        assert questions == expected_questions

    async def test_generate_questionnaire_raises_value_error_on_bad_json(self, qg_service: QuestionGenerationService, mock_llm_service: MagicMock):
        """Tests that a ValueError is raised if the LLM returns non-JSON text."""
        # Arrange
        mock_llm_service.generate_text = AsyncMock(return_value="This is not JSON.")

        # Act & Assert
        with pytest.raises(ValueError, match="The LLM returned an invalid format."):
            await qg_service.generate_questionnaire("jd", ["req"], MagicMock())