# tests/agents/job_post_agent/test_router.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# The 'api_client' fixture is provided by 'tests/conftest.py'

# A re-usable valid payload for the API
VALID_API_PAYLOAD = {
    "job_description": "This is a valid job description that is over 50 characters long.",
    "platform": "LinkedIn"
}

@pytest.fixture
def mock_service_class():
    """
    Patches the JobPostAgentService class itself.
    This is necessary because the service is instantiated *inside* the router.
    """
    # Create a mock for the service *instance*
    mock_service_instance = MagicMock()
    # Mock the async method 'generate_post' on the instance
    mock_service_instance.generate_post = AsyncMock(
        return_value={"result": "Generated post content"}
    )
    
    # Use patch to replace the *class* with a mock that returns our instance
    with patch("app.agents.job_post_agent.router.JobPostAgentService", 
               return_value=mock_service_instance) as mock_class:
        # We yield both the class mock and the instance mock
        yield mock_class, mock_service_instance

def test_generate_job_post_happy_path(api_client: TestClient, mock_service_class):
    """Tests the /generate endpoint for a successful 200 OK response."""
    mock_class, mock_instance = mock_service_class
    
    response = api_client.post("/api/v1/job-post-agent/generate", json=VALID_API_PAYLOAD)
    
    # Check the response
    assert response.status_code == 200
    assert response.json() == {
        "status": True,
        "platform": "LinkedIn",
        "generated_post": "Generated post content"
    }
    
    # Check that the service was instantiated and called correctly
    mock_class.assert_called_once() # With the llm_service
    mock_instance.generate_post.assert_called_once_with(
        platform="LinkedIn",
        job_description=VALID_API_PAYLOAD["job_description"]
    )

def test_generate_job_post_service_error(api_client: TestClient, mock_service_class):
    """Tests the router's generic 'except Exception' block."""
    mock_class, mock_instance = mock_service_class
    
    # Configure the mock to raise a generic error
    mock_instance.generate_post.side_effect = Exception("A_GENERIC_ERROR")
    
    response = api_client.post("/api/v1/job-post-agent/generate", json=VALID_API_PAYLOAD)
    
    # Check that the 500 error is handled correctly
    assert response.status_code == 500
    assert response.json() == {
        "detail": {"status": False, "error": "A_GENERIC_ERROR"}
    }

def test_generate_job_post_validation_error(api_client: TestClient):
    """Tests that a 422 is returned for bad input (e.g., invalid platform)."""
    bad_payload = {
        "job_description": "This string is long enough to pass validation.",
        "platform": "Google" # This platform is invalid
    }
    response = api_client.post("/api/v1/job-post-agent/generate", json=bad_payload)
    assert response.status_code == 422 # Unprocessable Entity