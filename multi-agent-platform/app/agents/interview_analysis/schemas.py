from pydantic import BaseModel
from typing import List


class TokenUsage(BaseModel):
    prompt_tokens: int
    response_tokens: int
    total_tokens: int
    audio_seconds: float


class FairnessMetrics(BaseModel):
    interviewer_sentiment: str


class FinalAnalysisResponse(BaseModel):
    user_id: str
    interviewer_analysis: str
    fairness_analysis: FairnessMetrics
    token_usage: TokenUsage