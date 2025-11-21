# tests/agents/criteria_agent/test_schema.py
import pytest
from pydantic import ValidationError
from app.agents.criteria_agent.schema import (
    CriteriaRequest, 
    _flatten_jd_object_to_string
)

# A re-usable example of the JD object for testing
EXAMPLE_JD_OBJECT = {
    "job_role": "AI/ML Engineer",
    "job_description": {
        "overview": "We are seeking an experienced AI/ML Engineer to join our team and work on cutting-edge machine learning projects.",
        "key_responsibilities": "Assist in the design, development, and deployment of machine learning models and AI solutions.",
        "required_skills": "Strong foundation in Python programming, experience with machine learning frameworks, data analysis skills.",
        "preferred_skills": "Familiarity with TensorFlow, PyTorch, and cloud platforms like AWS or GCP.",
        "minimum_qualification": "Bachelor's degree in Computer Science, Engineering, or related field with relevant experience.",
        # These keys exist but are empty, should be skipped
        "desired_attributes": None, 
        "languages": "",
        # This key is not in the key_order and should be skipped
        "extra_field": "This should not be in the output"
    }
}

def test_flatten_jd_object_to_string():
    """Tests that the helper function correctly flattens a JD object."""
    flat_string = _flatten_jd_object_to_string(EXAMPLE_JD_OBJECT)
    
    # Check that it contains the content in the correct order
    assert flat_string.startswith("Job Role: AI/ML Engineer")
    assert "Overview: We are seeking" in flat_string
    assert "Key Responsibilities: Assist in the design" in flat_string
    assert "Required Skills: Strong foundation in Python" in flat_string
    
    # Check that it skips empty/None fields
    assert "Desired Attributes" not in flat_string
    assert "Languages" not in flat_string
    
    # Check that it skips fields not in key_order
    assert "extra_field" not in flat_string

def test_criteria_request_with_string_jd():
    """Tests happy path with a plain string JD (must be at least 50 chars)."""
    data = {
        "jd_text": "This is a valid job description string that is longer than fifty characters to pass validation.",
        "target": "linkedin"
    }
    req = CriteriaRequest(**data)
    assert req.jd_text == data["jd_text"]
    assert req.target == "linkedin"

def test_criteria_request_with_dict_jd():
    """
    Tests the @field_validator's main purpose:
    - It should accept a dict for jd_text
    - It should flatten it into a string
    """
    data = {"jd_text": EXAMPLE_JD_OBJECT, "target": "all"}
    req = CriteriaRequest(**data)
    
    # The validator should have converted the dict to a string
    assert isinstance(req.jd_text, str)
    assert "Job Role: AI/ML Engineer" in req.jd_text
    assert "Overview: We are seeking" in req.jd_text
    # Should be longer than 50 chars after flattening
    assert len(req.jd_text) >= 50

def test_criteria_request_invalid_jd_type():
    """Tests that an invalid type for jd_text raises an error."""
    with pytest.raises(ValidationError) as exc_info:
        CriteriaRequest(jd_text=12345, target="indeed")
    
    # More flexible assertion - check if error is about jd_text
    error_str = str(exc_info.value).lower()
    assert "jd_text" in error_str or "string" in error_str

def test_criteria_request_invalid_target():
    """Tests that an unsupported target raises an error."""
    with pytest.raises(ValidationError):
        CriteriaRequest(
            jd_text="A valid string that is at least fifty characters long for validation purposes.",
            target="google"
        )

def test_criteria_request_string_too_short():
    """Tests that a string shorter than 50 characters raises an error."""
    with pytest.raises(ValidationError) as exc_info:
        CriteriaRequest(jd_text="Short string", target="linkedin")
    
    error_str = str(exc_info.value).lower()
    assert "at least 50 characters" in error_str