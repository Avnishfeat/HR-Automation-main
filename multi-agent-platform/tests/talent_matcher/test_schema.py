# tests/agents/talent_matcher/test_schemas.py
import pytest
from pydantic import ValidationError
from app.agents.talent_matcher.schemas import JobRequest, JobDescriptionDetail

# A valid dict that can be normalized
VALID_JD_DICT = {
    "required_skills": "Python",
    "preferred_skills": "PyTorch",
    "minimum_qualification": "Bachelor's",
    "languages": "English",
    "overview": "Test overview",
    "key_responsibilities": "Test responsibilities",
    "key_skills_and_qualifications": "Test skills",
    "desired_attributes": "Test attributes",
    "benefits": "Test benefits"
}

def test_job_request_with_dict():
    """
    Tests that the validator correctly normalizes a raw dictionary
    into a JobDescriptionDetail object.
    """
    request_data = {
        "job_role": "Engineer",
        "job_description": VALID_JD_DICT
    }
    
    req = JobRequest(**request_data)
    
    assert isinstance(req.job_description, JobDescriptionDetail)
    assert req.job_description.required_skills == "Python"

def test_job_request_with_object():
    """
    Tests that the model accepts a pre-built JobDescriptionDetail object.
    """
    jd_obj = JobDescriptionDetail(**VALID_JD_DICT)
    
    request_data = {
        "job_role": "Engineer",
        "job_description": jd_obj
    }
    
    req = JobRequest(**request_data)
    assert req.job_description == jd_obj

def test_job_request_missing_field_in_dict():
    """
    Tests that a dict missing a required field for JobDescriptionDetail
    will fail validation.
    """
    invalid_dict = VALID_JD_DICT.copy()
    del invalid_dict["required_skills"] # Remove a required field
    
    request_data = {
        "job_role": "Engineer",
        "job_description": invalid_dict
    }
    
    with pytest.raises(ValidationError) as e:
        JobRequest(**request_data)
    
    assert "required_skills" in str(e.value)

def test_job_request_invalid_type():
    """Tests that a non-dict/non-object fails."""
    request_data = {
        "job_role": "Engineer",
        "job_description": "This is just a string"
    }
    
    with pytest.raises(ValidationError):
        JobRequest(**request_data)