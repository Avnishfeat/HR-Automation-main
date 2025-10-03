from pydantic import BaseModel, Field
from typing import Optional

class ExampleAgentRequest(BaseModel):
    """Request schema for example agent"""
    query: str = Field(..., description="User query")
    context: Optional[str] = Field(None, description="Additional context")
    use_provider: str = Field("gemini", description="LLM provider to use")

class ExampleAgentResponse(BaseModel):
    """Response schema for example agent"""
    agent_name: str = "example_agent"
    result: str
    provider_used: str
