from pydantic import BaseModel
from typing import Optional

class TokenUsage(BaseModel):
    prompt_tokens: int
    response_tokens: int
    total_tokens: int
    audio_seconds: float

class HRAnalysisResponse(BaseModel):
    user_id: str
    interviewer_relevance_analysis: str
    company_guidelines_analysis: Optional[str] = None
    interviewer_sentiment: str
    token_usage: TokenUsage