from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime

class BaseResponse(BaseModel):
    """Base response model"""
    success: bool
    message: str
    data: Optional[Any] = None

class AgentRequest(BaseModel):
    """Base agent request model"""
    user_id: str = Field(..., description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    input_data: dict = Field(..., description="Input data for agent")

class AgentResponse(BaseModel):
    """Base agent response model"""
    agent_name: str
    response: Any
    metadata: Optional[dict] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
