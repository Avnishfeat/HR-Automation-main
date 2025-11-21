# tests/agents/criteria_agent/test_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

# A re-usable valid payload for the API - MUST BE AT LEAST 50 CHARACTERS
VALID_API_PAYLOAD = {
    "jd_text": "We are seeking an experienced software engineer with expertise in Python, FastAPI, and cloud technologies.",
    "target": "linkedin"
}

def test_health_check(api_client):
    """Tests the /health endpoint."""
    response = api_client.get("/api/v1/criteria/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "agent": "Criteria Agent"}

def test_generate_criteria_happy_path(api_client, mock_llm_service):
    """Tests the /generate endpoint for a successful 200 OK response."""
    # Mock the LLM service to return valid JSON
    mock_result = {"job_title": "Mocked Engineer", "keywords": ["python"]}
    mock_llm_service.generate_text = AsyncMock(return_value='{"job_title": "Mocked Engineer", "keywords": ["python"]}')
    
    response = api_client.post("/api/v1/criteria/generate", json=VALID_API_PAYLOAD)
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["status"] is True
    assert "criteria" in response_data
    assert "linkedin" in response_data["criteria"]

def test_generate_criteria_validation_error(api_client):
    """Tests that a 422 is returned for bad input (e.g., missing 'target')."""
    bad_payload = {"jd_text": "Missing target field but must be at least fifty characters long for validation."}
    response = api_client.post("/api/v1/criteria/generate", json=bad_payload)
    assert response.status_code == 422  # Unprocessable Entity

def test_generate_criteria_validation_error_short_string(api_client):
    """Tests that a 422 is returned for strings shorter than 50 characters."""
    bad_payload = {"jd_text": "Too short", "target": "linkedin"}
    response = api_client.post("/api/v1/criteria/generate", json=bad_payload)
    assert response.status_code == 422  # Unprocessable Entity

def test_generate_criteria_http_exception(api_client, mock_llm_service, monkeypatch):
    """Tests the router's 'except HTTPException' block."""
    # Mock the service function to raise HTTPException
    async def mock_service_error(*args, **kwargs):
        raise HTTPException(status_code=400, detail="Test Error")
    
    monkeypatch.setattr(
        "app.agents.criteria_agent.router.generate_criteria",
        mock_service_error
    )
    
    response = api_client.post("/api/v1/criteria/generate", json=VALID_API_PAYLOAD)
    
    assert response.status_code == 400
    response_data = response.json()
    assert response_data["status"] is False
    assert response_data["detail"] == "Test Error"

def test_generate_criteria_generic_exception(api_client, mock_llm_service, monkeypatch):
    """Tests the router's final 'except Exception' block."""
    # Mock the service function to raise a generic error
    async def mock_service_error(*args, **kwargs):
        raise Exception("Something went wrong")
    
    monkeypatch.setattr(
        "app.agents.criteria_agent.router.generate_criteria",
        mock_service_error
    )
    
    response = api_client.post("/api/v1/criteria/generate", json=VALID_API_PAYLOAD)
    
    assert response.status_code == 500
    response_data = response.json()
    assert response_data["status"] is False
    assert response_data["detail"] == "An internal server error occurred."