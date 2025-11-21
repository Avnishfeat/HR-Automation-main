# tests/agents/jd_agent/test_service.py
import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
from fastapi import HTTPException

# Import the services and schemas
from app.agents.jd_agent.service import (
    generate_job_description,
    _load_jd_template,
    _parse_llm_output_to_json
)
from app.agents.jd_agent.schema import JDInput
from app.services.llm_service import LLMService

# --- FIX APPLIED ---
# Removed: pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("raw_output, expected_dict", [
    # Test 1: Standard JSON
    ('{"key": "value", "nested": {"a": 1}}', {"key": "value", "nested": {"a": 1}}),
    
    # Test 2: JSON wrapped in ```json markdown
    ('```json\n{\n  "key": "value"\n}\n```', {"key": "value"}),
    
    # Test 3: JSON wrapped in ``` markdown
    ('```\n{\n  "key": "value"\n}\n```', {"key": "value"}),
    
    # Test 4: JSON with leading/trailing whitespace
    ('  \n{\n  "key": "value"\n}  \n', {"key": "value"}),
])
def test_parse_llm_output_to_json_happy_paths(raw_output, expected_dict):
    """Tests that the parser correctly handles various valid LLM outputs."""
    parsed = _parse_llm_output_to_json(raw_output)
    assert parsed == expected_dict

def test_parse_llm_output_to_json_invalid():
    """Tests that the parser raises an HTTPException on malformed JSON."""
    malformed_json = '{"key": "value", "unfinished":'
    with pytest.raises(HTTPException) as exc_info:
        _parse_llm_output_to_json(malformed_json)
    
    assert exc_info.value.status_code == 500
    assert "Could not parse the job description" in exc_info.value.detail

def test_load_jd_template_happy_path():
    """Tests loading a valid template (e.g., Data Analyst)."""
    mock_template_content = "This is a mock template for data visualization and reporting"
    
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=mock_template_content)):
            template = _load_jd_template("Data Analyst")
    
    assert "data visualization and reporting" in template

def test_load_jd_template_invalid_role():
    """Tests loading a template for a role that doesn't exist."""
    with pytest.raises(HTTPException) as exc_info:
        _load_jd_template("NonExistent Role")
    
    assert exc_info.value.status_code == 400
    assert "Job role 'NonExistent Role' not available" in exc_info.value.detail

def test_load_jd_template_file_missing(monkeypatch):
    """Tests for a role that is in ROLE_FILE_MAP but missing on disk."""
    # Mock os.path.exists to return False
    monkeypatch.setattr("os.path.exists", lambda x: False)
    
    with pytest.raises(HTTPException) as exc_info:
        _load_jd_template("Data Analyst")  # Use a known valid role
        
    assert exc_info.value.status_code == 500
    assert "Template file missing for role" in exc_info.value.detail

# --- FIX APPLIED ---
@pytest.mark.asyncio
async def test_generate_job_description_happy_path():
    """
    Tests the main service function with a mocked LLMService.
    """
    mock_llm_service = MagicMock(spec=LLMService)
    
    mock_llm_output = json.dumps({
        "overview": "This is a test JD.",
        "required_skills": "SQL, Python"
    })
    mock_llm_service.generate_text = AsyncMock(return_value=mock_llm_output)
    
    payload = JDInput(
        job_role="Data Analyst",
        experience="3-5 years",
        requirements="SQL and Python"
    )
    
    mock_template = "Mock template content"
    with patch("app.agents.jd_agent.service._load_jd_template", return_value=mock_template):
        result = await generate_job_description(payload, mock_llm_service)
    
    assert result == json.loads(mock_llm_output)
    
    mock_llm_service.generate_text.assert_called_once()
    call_args = mock_llm_service.generate_text.call_args[0][0]
    
    assert "**Job Role:** Data Analyst" in call_args
    assert "Experience: 3-5 years" in call_args
    assert "Requirements: SQL and Python" in call_args
    assert "FOLLOW THIS RESPONSE JSON STRUCTURE" in call_args

# --- FIX APPLIED ---
@pytest.mark.asyncio
async def test_generate_job_description_llm_parse_error():
    """Tests that an HTTPException is raised if the LLM returns bad JSON."""
    mock_llm_service = MagicMock(spec=LLMService)
    mock_llm_service.generate_text = AsyncMock(return_value="This is not JSON")
    
    payload = JDInput(
        job_role="Data Analyst",
        experience="3-5 years",
        requirements="SQL"
    )
    
    with patch("app.agents.jd_agent.service._load_jd_template", return_value="Mock template"):
        with pytest.raises(HTTPException) as exc_info:
            await generate_job_description(payload, mock_llm_service)
    
    assert exc_info.value.status_code == 500
    assert "Could not parse the job description" in exc_info.value.detail