# tests/agents/criteria_agent/test_service.py
import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from fastapi import HTTPException

# Import the services and schemas
from app.agents.criteria_agent.service import (
    _load_criteria_template,
    _build_prompt,
    _generate_for_single_target,
    generate_criteria
)
from app.agents.criteria_agent.schema import CriteriaRequest
from app.services.llm_service import LLMService

# --- FIX 2 & 3 APPLIED HERE ---
# Changed MOCK_JD_TEXT to be longer than 50 characters
MOCK_JD_TEXT = "This is a mock job description for a Python Developer, it must be at least 50 characters long."
MOCK_LINKEDIN_SCHEMA = {"job_title": "string", "keywords": ["list"]}

@pytest.fixture
def mock_llm():
    """Provides a re-usable mock LLMService."""
    llm = MagicMock(spec=LLMService)
    llm.generate_text = AsyncMock()
    return llm

# We remove the global pytestmark and add @pytest.mark.asyncio manually
# (This fixes the warnings from your last run)

def test_load_template_happy_path(monkeypatch):
    """Tests that a valid platform loads the correct JSON file."""
    mock_open_context = patch("builtins.open", MagicMock()).start()
    mock_json_load = patch("json.load", return_value=MOCK_LINKEDIN_SCHEMA).start()
    
    monkeypatch.setattr("os.path.exists", lambda x: True)
    
    schema = _load_criteria_template("linkedin")
    
    assert schema == MOCK_LINKEDIN_SCHEMA
    
    # --- FIX 1 APPLIED HERE ---
    # Replaced pytest.string_containing with ANY and a path check
    mock_open_context.assert_called_with(ANY, "r", encoding="utf-8")
    call_path = mock_open_context.call_args[0][0]
    assert "linkedin.json" in call_path
    
    patch.stopall() # Stop the patches

def test_load_template_unsupported_platform():
    """Tests that an invalid platform name raises a 400 error."""
    with pytest.raises(HTTPException) as e:
        _load_criteria_template("google")
    assert e.value.status_code == 400 
    assert "Unsupported platform" in e.value.detail

def test_load_template_file_missing(monkeypatch):
    """Tests that a missing file raises a 500 error."""
    monkeypatch.setattr("os.path.exists", lambda x: False)
    
    with pytest.raises(HTTPException) as e:
        _load_criteria_template("linkedin")
    assert e.value.status_code == 500 
    assert "Schema file not found" in e.value.detail

@patch("app.agents.criteria_agent.service._load_criteria_template", 
       return_value=MOCK_LINKEDIN_SCHEMA)
def test_build_prompt(mock_load_template):
    """Tests that the prompt is built with the schema and JD."""
    prompt = _build_prompt("linkedin", MOCK_JD_TEXT)
    
    assert "JSON Schema to Follow:" in prompt
    assert json.dumps(MOCK_LINKEDIN_SCHEMA, indent=2) in prompt 
    assert "Job Description:" in prompt
    assert MOCK_JD_TEXT in prompt

@pytest.mark.asyncio
async def test_generate_for_single_target_happy(mock_llm):
    """Tests that a clean JSON response is parsed correctly."""
    mock_llm.generate_text.return_value = '{"job_title": "Engineer"}'
    
    result = await _generate_for_single_target("linkedin", MOCK_JD_TEXT, mock_llm)
    
    assert result == {"job_title": "Engineer"}

@pytest.mark.asyncio
async def test_generate_for_single_target_cleans_markdown(mock_llm):
    """Tests that the service cleans up markdown fences.""" 
    mock_llm.generate_text.return_value = '```json\n{"key": "value"}\n```'
    
    result = await _generate_for_single_target("linkedin", MOCK_JD_TEXT, mock_llm)
    
    assert result == {"key": "value"}

@pytest.mark.asyncio
async def test_generate_for_single_target_json_error(mock_llm):
    """Tests that bad JSON returns a structured error."""
    raw_output = "This is not JSON"
    mock_llm.generate_text.return_value = raw_output
    
    result = await _generate_for_single_target("linkedin", MOCK_JD_TEXT, mock_llm)
    
    assert result == {
        "error": "Failed to generate valid JSON.", 
        "raw_output": raw_output
    }

@pytest.mark.asyncio
async def test_generate_criteria_single_target(mock_llm):
    """Tests that 'target=linkedin' only calls the LLM once."""
    payload = CriteriaRequest(jd_text=MOCK_JD_TEXT, target="linkedin")
    mock_llm.generate_text.return_value = '{"job_title": "Engineer"}'
    
    with patch("app.agents.criteria_agent.service._generate_for_single_target", 
             new_callable=AsyncMock) as mock_helper:
        
        mock_helper.return_value = {"job_title": "Engineer"}
        
        result = await generate_criteria(payload, mock_llm)
        
        mock_helper.assert_called_once_with("linkedin", MOCK_JD_TEXT, mock_llm)
        assert result == {"linkedin": {"job_title": "Engineer"}}

@pytest.mark.asyncio
async def test_generate_criteria_all_targets(mock_llm):
    """Tests that 'target=all' calls all targets concurrently.""" 
    payload = CriteriaRequest(jd_text=MOCK_JD_TEXT, target="all")
    
    async def mock_helper_side_effect(platform, jd, llm):
        if platform == "linkedin":
            return {"job_title": "L"}
        if platform == "indeed":
            return {"keywords": "I"}
        if platform == "naukri":
            return {"role": "N"}
    
    with patch("app.agents.criteria_agent.service._generate_for_single_target", 
             side_effect=mock_helper_side_effect) as mock_helper:
        
        result = await generate_criteria(payload, mock_llm)
        
        assert mock_helper.call_count == 3
        
        expected_result = {
            "linkedin": {"job_title": "L"},
            "indeed": {"keywords": "I"},
            "naukri": {"role": "N"}
        }
        assert result == expected_result