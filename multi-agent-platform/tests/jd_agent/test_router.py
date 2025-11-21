import json
from unittest.mock import AsyncMock

# Note: We no longer import TestClient, app, or dependencies here.
# They are provided by the fixtures in conftest.py

def test_health_check(api_client):
    """Tests the /health endpoint."""
    response = api_client.get("/api/v1/jd/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "agent": "JD Agent"}

def test_generate_jd_happy_path(api_client, mock_llm_service):
    """Tests the /generate endpoint with valid input."""
    # 1. Configure the mock for this specific test
    mock_llm_output = {
        "overview": "A generated JD for a Data Analyst",
        "key_responsibilities": "Analyze data"
    }
    mock_llm_service.generate_text = AsyncMock(return_value=json.dumps(mock_llm_output))
    
    # 2. Define the API payload
    api_payload = {
        "job_role": "Data Analyst",
        "experience": "2 years",
        "requirements": "SQL"
    }
    
    # 3. Call the API endpoint
    response = api_client.post("/api/v1/jd/generate", json=api_payload)
    
    # 4. Assert the HTTP response
    assert response.status_code == 200
    
    # 5. Assert the response body structure
    data = response.json()
    assert data["status"] is True
    assert data["job_role"] == "Data Analyst"
    assert data["job_description"] == mock_llm_output

def test_generate_jd_validation_error(api_client):
    """Tests the API for a 422 Unprocessable Entity error on bad input."""
    # 1. Define an invalid payload (invalid job_role)
    api_payload = {
        "job_role": "Spaceship Pilot", # Not in ALLOWED_ROLES
        "experience": "2 years",
        "requirements": "SQL"
    }
    
    # 2. Call the API
    response = api_client.post("/api/v1/jd/generate", json=api_payload)
    
    # 3. Assert the 422 error
    assert response.status_code == 422
    data = response.json()
    assert "not a supported job role" in str(data["detail"])

def test_generate_jd_internal_server_error(api_client, mock_llm_service):
    """Tests the API's service-level 500 error handler."""
    # 1. Configure the mock to raise an unexpected error
    mock_llm_service.generate_text = AsyncMock(side_effect=Exception("Something broke!"))
    
    # 2. Define a valid payload
    api_payload = {
        "job_role": "Data Analyst",
        "experience": "2 years",
        "requirements": "SQL"
    }
    
    # 3. Call the API
    response = api_client.post("/api/v1/jd/generate", json=api_payload)
    
    # 4. Assert the 500 error from the service's handler
    assert response.status_code == 500
    assert response.json() == {
        "status": False,
        "detail": "An internal error occurred in the JD agent."
    }

# --- NEW TEST ADDED FOR 100% COVERAGE ---

def test_generate_jd_router_catches_generic_exception(api_client, monkeypatch):
    """
    Tests that the router's own generic 'except Exception' block is triggered
    if the service call raises an unexpected, non-HTTP error.
    """
    # 1. Mock the SERVICE FUNCTION (not the LLM) to raise a generic Exception
    #    This simulates a failure *before* the service's own error handling.
    def mock_raise_exception(*args, **kwargs):
        raise Exception("A generic, non-HTTP error")

    # Use monkeypatch to replace the real function with our mock
    monkeypatch.setattr(
        "app.agents.jd_agent.router.generate_job_description", 
        mock_raise_exception
    )

    # 2. Define a valid payload
    api_payload = {
        "job_role": "Data Analyst",
        "experience": "2 years",
        "requirements": "SQL"
    }

    # 3. Call the API
    response = api_client.post("/api/v1/jd/generate", json=api_payload)

    # 4. Assert the generic 500 error from the router's handler
    assert response.status_code == 500
    assert response.json() == {
        "status": False,
        "detail": "An internal server error occurred."
    }