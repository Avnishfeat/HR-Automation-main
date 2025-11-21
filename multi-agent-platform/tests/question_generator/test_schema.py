# File: tests/agents/question_generator/test_schema.py

import pytest
from pydantic import ValidationError
from app.agents.question_generator.schema import (
    QuestionnaireRequest,
    QuestionnaireResponse,
    ErrorResponse
)

def test_questionnaire_request_success():
    """Tests a valid QuestionnaireRequest model."""
    data = {
        "jd_text": "Job description here",
        "requirements": ["Python", "FastAPI"],
        "resume_text": "Resume text here"
    }
    req = QuestionnaireRequest(**data)
    assert req.jd_text == data["jd_text"]
    assert req.requirements == data["requirements"]

def test_questionnaire_request_fails_empty_requirements():
    """Tests that the request fails if requirements list is empty."""
    data = {
        "jd_text": "Job description here",
        "requirements": [], # This violates min_length=1
        "resume_text": "Resume text here"
    }
    with pytest.raises(ValidationError):
        QuestionnaireRequest(**data)

def test_questionnaire_response_defaults():
    """Tests that QuestionnaireResponse sets status=True by default."""
    questions = ["Question 1?", "Question 2?"]
    resp = QuestionnaireResponse(questions=questions)
    assert resp.status is True
    assert resp.questions == questions

def test_error_response_defaults():
    """Tests that ErrorResponse sets status=False by default."""
    detail = "An error occurred"
    resp = ErrorResponse(detail=detail)
    assert resp.status is False
    assert resp.detail == detail