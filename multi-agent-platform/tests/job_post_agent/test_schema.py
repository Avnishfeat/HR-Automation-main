# tests/agents/job_post_agent/test_schemas.py
import pytest
from pydantic import ValidationError
from app.agents.job_post_agent.schemas import JobPostRequest, _flatten_jd_object_to_string

# A re-usable example of the JD object for testing
EXAMPLE_JD_OBJECT = {
    "job_role": "AI/ML Engineer",
    "job_description": {
        "overview": "We are seeking...",
        "key_responsibilities": "Assist in the design...",
        "required_skills": "Strong foundation in Python..."
    }
}

# A re-usable valid string JD
VALID_STRING_JD = "This is a valid job description string that is longer than fifty characters to pass validation."

def test_flatten_jd_object_to_string():
    """Tests that the helper function correctly flattens a JD object."""
    flat_string = _flatten_jd_object_to_string(EXAMPLE_JD_OBJECT)
    
    assert flat_string.startswith("Job Role: AI/ML Engineer")
    assert "Overview: We are seeking..." in flat_string
    assert "Key Responsibilities: Assist in the design..." in flat_string

def test_job_post_request_with_string_jd():
    """Tests happy path with a plain string JD."""
    data = {"job_description": VALID_STRING_JD, "platform": "LinkedIn"}
    req = JobPostRequest(**data)
    assert req.job_description == VALID_STRING_JD
    assert req.platform == "LinkedIn"

def test_job_post_request_with_dict_jd():
    """Tests the @field_validator's ability to flatten a dict."""
    data = {"job_description": EXAMPLE_JD_OBJECT, "platform": "Indeed"}
    req = JobPostRequest(**data)
    
    # The validator should have converted the dict to a string
    assert isinstance(req.job_description, str)
    assert "Job Role: AI/ML Engineer" in req.job_description

def test_job_post_request_string_too_short():
    """Tests that a string shorter than 50 characters fails."""
    with pytest.raises(ValidationError) as e:
        JobPostRequest(job_description="Short string", platform="Naukri")
    assert "at least 50 characters" in str(e.value)

def test_job_post_request_invalid_platform():
    """Tests that an unsupported platform raises an error."""
    with pytest.raises(ValidationError):
        JobPostRequest(job_description=VALID_STRING_JD, platform="Google")

def test_job_post_request_invalid_type():
    """Tests that an invalid type for jd_description raises an error."""
    with pytest.raises(ValidationError, match="job_description must be a string"):
        JobPostRequest(job_description=12345, platform="LinkedIn")

def test_job_post_request_missing_fields():
    """Tests that missing required fields raises an error."""
    with pytest.raises(ValidationError, match="job_description"):
        JobPostRequest(platform="LinkedIn")
        
    with pytest.raises(ValidationError, match="platform"):
        JobPostRequest(job_description=VALID_STRING_JD)