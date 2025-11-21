import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app
# Import the real service and the *new* dependency getter
from app.agents.talent_matcher.service import TalentMatcherService
from app.agents.talent_matcher.router import get_talent_matcher_service

# A valid payload to reuse in tests
VALID_PAYLOAD = {
    "job_role": "Engineer",
    "job_description": {
        "required_skills": "Python", "preferred_skills": "", "minimum_qualification": "",
        "languages": "", "overview": "", "key_responsibilities": "",
        "key_skills_and_qualifications": "", "desired_attributes": "", "benefits": ""
    }
}

# --- Mock Fixture ---
@pytest.fixture
def mock_service():
    """Creates a mock TalentMatcherService."""
    return MagicMock(spec=TalentMatcherService)

@pytest.fixture(autouse=True)
def override_dependency(mock_service):
    """
    Overrides the 'get_talent_matcher_service' dependency for all tests
    in this file.
    """
    def override_getter():
        return mock_service
    
    app.dependency_overrides[get_talent_matcher_service] = override_getter
    yield
    # Clean up
    app.dependency_overrides.clear()
# --- End of Fixtures ---


def test_health_check(api_client: TestClient):
    """Tests the health check endpoint."""
    response = api_client.get("/api/v1/talent_matcher/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "agent": "Talent Matcher"}

def test_match_job_happy_path(api_client: TestClient, mock_service: MagicMock):
    """Tests the /match-job endpoint for a successful 200 OK response."""
    mock_return = [
        {"employee_id": "1", "name": "Alice", "title": "Dev", "score": 0.9, "experience_years": 5, "reasons": ["python"]}
    ]
    mock_service.match.return_value = mock_return
    
    response = api_client.post("/api/v1/talent_matcher/match-job", json=VALID_PAYLOAD)
    
    assert response.status_code == 200
    expected_json = {
        "status": True,
        "data": mock_return,
        "message": "Found 1 matching candidates for Engineer"
    }
    assert response.json() == expected_json
    mock_service.match.assert_called_once()

def test_match_job_http_exception(api_client: TestClient, mock_service: MagicMock):
    """Tests that an HTTPException from the service is re-raised."""
    mock_service.match.side_effect = HTTPException(status_code=400, detail="A specific bad request")
    
    response = api_client.post("/api/v1/talent_matcher/match-job", json=VALID_PAYLOAD)
    
    assert response.status_code == 400
    assert response.json() == {"detail": "A specific bad request"}

def test_match_job_generic_exception(api_client: TestClient, mock_service: MagicMock):
    """Tests that a generic Exception is caught and returned as a 500."""
    mock_service.match.side_effect = Exception("A non-HTTP error")
    
    response = api_client.post("/api/v1/talent_matcher/match-job", json=VALID_PAYLOAD)
    
    assert response.status_code == 500
    assert "An internal server error occurred: A non-HTTP error" in response.json()["detail"]

def test_get_service_is_cached(api_client: TestClient, mock_service: MagicMock):
    """
    Tests that the service is loaded only once (cached).
    """
    # We need to reset the dependency override for this specific test
    # to use the *real* getter, but have the *real* getter load our mock
    
    # This removes the auto-use override for this one test
    real_getter = app.dependency_overrides.pop(get_talent_matcher_service)

    # We patch the service *inside* the router to see how often it's called
    with patch("app.agents.talent_matcher.router.TalentMatcherService", return_value=mock_service) as MockServiceClass:
        
        # --- FIX APPLIED ---
        # We DO NOT put the override back. We want FastAPI to use the
        # real getter, which will then hit our patch.
        # DELETED: app.dependency_overrides[get_talent_matcher_service] = real_getter

        # Call 1: This should trigger the service init
        api_client.post("/api/v1/talent_matcher/match-job", json=VALID_PAYLOAD)
        # Call 2: This should use the cached service
        api_client.post("/api/v1/talent_matcher/match-job", json=VALID_PAYLOAD)

        # Check that TalentMatcherService() was only called ONCE
        MockServiceClass.assert_called_once()
        # Check that service.match() was called twice
        assert mock_service.match.call_count == 2