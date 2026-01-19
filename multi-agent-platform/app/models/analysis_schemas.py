
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class QuestionAnalysis(BaseModel):
    """Schema for individual question-answer analysis from transcript"""
    timestamp: str = Field(..., description="Timestamp of the question")
    question: str = Field(..., description="Interview question asked")
    answer: str = Field(..., description="Candidate's answer")
    analysis: str = Field(..., description="Detailed analysis of the response")
    relevance_to_resume: str = Field(..., description="How question relates to resume")
    answer_quality: str = Field(..., description="Quality rating (Poor/Fair/Good/Excellent)")
    technical_accuracy: str = Field(..., description="Technical correctness assessment")
    score: float = Field(..., ge=0, le=10, description="Score out of 10")

    class Config:
        pass

class OverallAnalysis(BaseModel):
    """Schema for transcript analysis"""
    user_id: Optional[str] = Field(None, description="Candidate user ID")
    session_id: str = Field(..., description="Interview session ID")
    interview_date: Optional[str] = Field(None, description="Interview date")
    questions_analyzed: List[QuestionAnalysis] = Field(..., description="List of Q&A analyses")
    overall_summary: str = Field(..., description="Overall summary")
    strengths: List[str] = Field(..., description="Candidate's strengths")
    weaknesses: List[str] = Field(..., description="Areas for improvement")
    resume_alignment_score: float = Field(..., ge=0, le=10)
    communication_score: float = Field(..., ge=0, le=10)
    technical_knowledge_score: float = Field(..., ge=0, le=10)
    overall_score: float = Field(..., ge=0, le=10)
    recommendations: List[str] = Field(...)
    #New fields for answer authenticity detection
    authenticity_score: float = Field(..., ge=0, le=10, description="10=Natural, 1=Completely Scripted/AI")
    is_scripted: bool = Field(..., description="Flag if significant AI usage is suspected")
    authenticity_analysis: str = Field(..., description="Reasoning behind the authenticity score")

    class Config:
        pass

class VoiceAuthenticity(BaseModel):
    is_human: bool
    confidence_score: float = Field(..., ge=1, le=10)
    classification: str # "human_natural/synthetic_robotic/uncertain"
    detection_basis: List[str]

class AudioQualityAnalysis(BaseModel):
    recording_quality: str # "poor/fair/good/excellent"
    background_noise_level: str # "none/low/moderate/high"
    clarity_score: float = Field(..., ge=1, le=10)
    sample_consistency: str # "consistent/variable/inconsistent"

class HumanCharacteristics(BaseModel):
    natural_prosody: bool
    emotional_variance: bool
    breathing_patterns: bool
    natural_pauses: bool
    voice_modulation: bool

class SyntheticIndicators(BaseModel):
    robotic_tone: bool
    uniform_pitch: bool
    mechanical_rhythm: bool
    tts_artifacts: bool
    unnatural_pacing: bool

class OverallAssessment(BaseModel):
    verdict: str # "authentic_human/likely_human/uncertain/likely_synthetic/synthetic_confirmed"
    confidence_percentage: float = Field(..., ge=0, le=100)
    risk_level: str # "low/medium/high"
    recommendation: str # "approve/review_manually/flag_for_investigation"

class IntegrityAnalysis(BaseModel):
    """Deep forensic analysis for cheating detection"""
    
    # Replay / Pre-recorded Voice Detection
    playback_detected: bool = Field(..., description="True if audio sounds like a recording played into the mic")
    playback_confidence: float = Field(..., ge=0, le=10, description="Confidence that audio is pre-recorded")
    playback_evidence: List[str] = Field(..., description="List of artifacts found (e.g. 'electronic hum', 'double reverb')")
    
    # Whisper / External Help Detection
    whisper_detected: bool = Field(..., description="True if a second person is heard whispering")
    multiple_speakers_detected: bool = Field(..., description="True if more than one voice is present")
    whisper_confidence: float = Field(..., ge=0, le=10)
    whisper_segments: List[str] = Field(..., description="Approximate timing or description of whispers")

class VoiceAuthenticityResult(BaseModel):
    """Schema for the detailed JSON result from Gemini voice detection."""
    voice_authenticity: VoiceAuthenticity
    audio_quality_analysis: AudioQualityAnalysis
    human_characteristics_detected: HumanCharacteristics
    synthetic_indicators: SyntheticIndicators
    integrity_analysis: IntegrityAnalysis
    overall_assessment: OverallAssessment
    detailed_observations: str
    samples_analyzed: int

class VoiceDetectionReport(BaseModel):
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    analysis_timestamp: str
    samples_analyzed: Optional[int] = None
    detection_result: Optional[VoiceAuthenticityResult] = None
    raw_response: Optional[str] = None
    status: str # "success" or "parse_error" or "error"
    error: Optional[str] = None
    error_message: Optional[str] = None # For _create_error_result

# --- NEW: Schema for Combined Analysis ---
class ScoringMetadata(BaseModel):
    """Metadata about how scores were calculated"""
    behavioral_weight: float = Field(0.4, ge=0, le=1, description="Weight for behavioral score")
    transcript_weight: float = Field(0.5, ge=0, le=1, description="Weight for transcript score")
    voice_weight: float = Field(0.1, ge=0, le=1, description="Weight for voice authenticity score")
    communication_weight: float = Field(0.4, ge=0, le=1, description="Weight for communication sub-score within transcript")
    technical_weight: float = Field(0.6, ge=0, le=1, description="Weight for technical sub-score within transcript")
    confidence_level: str = Field(..., description="Confidence level: high/medium/low based on data quality")
    data_quality_score: float = Field(..., ge=0, le=1, description="Overall data quality score (0-1)")

class CombinedAnalysisReport(BaseModel):
    """Schema for the final combined analysis report"""
    session_id: str
    candidate_id: str
    interview_date: Optional[str]

    # Scores
    behavioral_score: Optional[float] = Field(None, ge=0, le=10, description="Overall score from behavioral analysis (e.g., based on metrics)")
    transcript_overall_score: float = Field(..., ge=0, le=10, description="Overall score from transcript analysis")
    transcript_communication_score: float = Field(..., ge=0, le=10)
    transcript_technical_score: float = Field(..., ge=0, le=10)
    voice_authenticity_score: Optional[float] = Field(None, ge=0, le=10, description="Numeric score derived from voice analysis")
    final_weighted_score: float = Field(..., ge=0, le=10, description="Combined weighted score")
    
    # Scoring metadata
    scoring_metadata: Optional[ScoringMetadata] = Field(None, description="Metadata about score calculation")
    confidence_interval_lower: Optional[float] = Field(None, ge=0, le=10, description="Lower bound of confidence interval")
    confidence_interval_upper: Optional[float] = Field(None, ge=0, le=10, description="Upper bound of confidence interval")

    # Summaries & Lists
    behavioral_summary: Optional[str] = Field(None, description="Summary from behavioral analysis")
    transcript_summary: str
    combined_strengths: List[str]
    combined_weaknesses: List[str]
    combined_recommendations: List[str]
    
    # --- NEW: Voice Analysis Result ---
    voice_authenticity_analysis: Optional[VoiceDetectionReport] = Field(None, description="Result from voice authenticity detection")

    # --- NEW: Background Person Detection ---
    background_person_detection_count: int = Field(0, ge=0, description="Number of frames where additional persons were detected in background")

    # --- NEW: Voice Gender Mismatch Detection ---
    expected_gender: Optional[str] = Field(None, description="Expected gender from visual/name analysis (male/female/uncertain)")
    expected_gender_source: Optional[str] = Field(None, description="Source of expected gender: visual, name_heuristic, or none")
    detected_voice_gender: Optional[str] = Field(None, description="Voice gender detected from audio (male/female/uncertain)")
    voice_gender_mismatch: bool = Field(False, description="True if voice gender doesn't match expected gender")

    # --- NEW: Reconnection Tracking ---
    reconnection_count: int = Field(0, ge=0, description="Number of times candidate disconnected and rejoined during interview")
