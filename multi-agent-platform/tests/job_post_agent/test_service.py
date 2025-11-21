# tests/agents/job_post_agent/test_service.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.agents.job_post_agent.service import JobPostAgentService
from app.services.llm_service import LLMService

# We need this for all async tests in this file
pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_llm():
    """Provides a re-usable mock LLMService."""
    llm = MagicMock(spec=LLMService)
    # Set up the async method 'generate_text'
    llm.generate_text = AsyncMock(return_value="Mocked LLM Output")
    return llm

@pytest.fixture
def service(mock_llm):
    """Provides a service instance initialized with the mock LLM."""
    return JobPostAgentService(mock_llm)

@pytest.mark.parametrize("platform, expected_prompt_snippet", [
    ("LinkedIn", "job post for LinkedIn"),
    ("Indeed", "job post for Indeed"),
    ("Naukri", "job post for Naukri.com")
])
async def test_generate_post_happy_path(service, mock_llm, platform, expected_prompt_snippet):
    """Tests that the correct prompt template is used for each platform."""
    jd = "A job description."
    result = await service.generate_post(platform=platform, job_description=jd)
    
    # Check that the return value is correct
    assert result == {"result": "Mocked LLM Output"}
    
    # Check that the LLM was called with the correct prompt
    mock_llm.generate_text.assert_called_once()
    
    # --- FIX APPLIED HERE ---
    # We look for the 'prompt' keyword argument in call_args[1]
    called_prompt = mock_llm.generate_text.call_args[1]['prompt']
    
    assert expected_prompt_snippet in called_prompt
    assert jd in called_prompt

async def test_generate_post_invalid_platform(service):
    """Tests that an unsupported platform raises a ValueError."""
    with pytest.raises(ValueError, match="Invalid platform specified."):
        await service.generate_post(platform="Google", job_description="A job desc.")