# File: tests/models/test_common.py

import pytest
from pydantic import ValidationError
from datetime import datetime
from app.models.common import BaseResponse, AgentRequest, AgentResponse

def test_base_response():
    """Covers BaseResponse model."""
    resp = BaseResponse(success=True, message="OK", data={"key": "value"})
    assert resp.success is True
    assert resp.data == {"key": "value"}
    assert resp.model_dump() == {
        "success": True, 
        "message": "OK", 
        "data": {"key": "value"}
    }

def test_agent_request():
    """Covers AgentRequest model."""
    req = AgentRequest(user_id="123", session_id="abc", input_data={"prompt": "hi"})
    assert req.user_id == "123"
    assert req.session_id == "abc"

def test_agent_request_validation_error():
    """Covers AgentRequest model validation."""
    with pytest.raises(ValidationError):
        AgentRequest(input_data={}) # Missing user_id

def test_agent_response():
    """Covers AgentResponse model and its timestamp default_factory."""
    before = datetime.utcnow()
    resp = AgentResponse(
        agent_name="test_agent", 
        response="hello", 
        metadata={"key": "val"}
    )
    after = datetime.utcnow()
    
    assert resp.agent_name == "test_agent"
    assert resp.metadata == {"key": "val"}
    assert before <= resp.timestamp <= after