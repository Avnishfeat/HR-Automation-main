import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Import your app and dependencies
from app.main import app
from app.core.dependencies import get_llm_service
from app.services.llm_service import LLMService

@pytest.fixture(scope="session")
def mock_llm_service():
    """
    A session-scoped fixture that creates a single mock LLMService.
    This mock will be shared across all tests in the session.
    """
    mock_llm = MagicMock(spec=LLMService)
    
    # Set a default async mock for the 'generate_text' method
    default_output = json.dumps({"default": "mock output"})
    mock_llm.generate_text = AsyncMock(return_value=default_output)
    
    yield mock_llm

@pytest.fixture(scope="module")
def api_client(mock_llm_service):
    """
    A module-scoped fixture that creates a TestClient.
    It applies the mock_llm_service override *before* creating the client.
    """
    
    # Define the dependency override
    async def override_get_llm_service():
        return mock_llm_service

    # Apply the override to the app (FIXED TYPO)
    app.dependency_overrides[get_llm_service] = override_get_llm_service
    
    # Create the client and yield it for tests
    with TestClient(app) as client:
        yield client
    
    # Clean up: remove the override after tests in the module are done (FIXED TYPO)
    app.dependency_overrides.clear()