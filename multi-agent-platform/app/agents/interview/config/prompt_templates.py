from typing import Dict, Any

class PromptTemplates:
    """Central repository for all analysis prompts."""
    
    VERSION = "3.0.0" # Updated for single JSON output
    
    @staticmethod
    def behavioral_screening(num_images: int) -> str:
        """Prompt for behavioral screening analysis (optimized for fairness)."""
        return f"""You are a helpful and fair Recruitment Assistant. 

I am providing you with {num_images} sequential snapshots captured throughout a virtual screening interview (one snapshot every 5 seconds). 

Your task is to evaluate the candidate's **Professional Presence** and **Engagement**.

**IMPORTANT CONTEXT**: 
1. These are static snapshots, not video. Do not over-analyze micro-expressions.
2. This is a screening interview. Slight nervousness is normal.
3. **Identity Check**: Verify the same person is present.

**CRITICAL**: You must provide your response in the exact JSON format specified below.

```json
{{
  "identity_consistency": {{
    "is_consistent": <true/false>,
    "confidence_score": <1-10>,
    "observations": "Briefly confirm if the same person is visible."
  }},
  "professionalism_check": {{
    "attire_appropriateness": "casual/smart_casual/professional/inappropriate",
    "environment_check": "clean/cluttered/distracting/professional",
    "camera_angle": "good/poor/obscured",
    "overall_professionalism_score": <1-10>
  }},
  "engagement_metrics": {{
    "eye_contact_quality": "good/average/poor",
    "looking_at_screen_frequency": "most_of_time/often/rarely",
    "facial_expression_demeanor": "positive/neutral/bored/anxious",
    "attentiveness_score": <1-10>
  }},
  "potential_concerns": {{
    "detected": <true/false>,
    "suspicion_of_reading_script": "unlikely/possible/highly_likely",
    "multiple_people_detected": <true/false>,
    "notes": "Only add notes if there is a genuine concern."
  }},
  "screening_outcome": {{
    "overall_confidence_score": <1-10>,
    "recommendation": "proceed/proceed_with_caution/flag_for_review",
    "summary": "A fair, 2-sentence summary of their visual presence.",
    "key_positive_traits": ["trait1", "trait2"],
    "areas_to_probe": ["area1"]
  }}
}}
```

Provide ONLY the JSON output, no additional text."""
    
    @staticmethod
    def voice_authenticity(num_samples: int) -> str:
        """Prompt for voice authenticity detection."""
        return f"""You are an expert audio forensics analyst specializing in voice authenticity detection.

I am providing you with {num_samples} audio samples from a candidate's interview responses. Your task is to determine if the voice is:
1. **Human (Natural)** - Authentic human voice
2. **Synthetic (AI-generated/Text-to-Speech)** - Computer-generated voice

**CRITICAL**: Provide response in exact JSON format.

Analyze for:
- Voice naturalness and human characteristics
- Robotic/synthetic artifacts
- Speech patterns and prosody
- Background noise and recording quality
- Consistency across samples

```json
{{
  "voice_authenticity": {{
    "is_human": <true/false>,
    "confidence_score": <1-10>,
    "classification": "human_natural/synthetic_robotic/uncertain",
    "detection_basis": ["characteristic1", "characteristic2"]
  }},
  "audio_quality_analysis": {{
    "recording_quality": "poor/fair/good/excellent",
    "background_noise_level": "none/low/moderate/high",
    "clarity_score": <1-10>,
    "sample_consistency": "consistent/variable/inconsistent"
  }},
  "human_characteristics_detected": {{
    "natural_prosody": <true/false>,
    "emotional_variance": <true/false>,
    "breathing_patterns": <true/false>,
    "natural_pauses": <true/false>,
    "voice_modulation": <true/false>
  }},
  "synthetic_indicators": {{
    "robotic_tone": <true/false>,
    "uniform_pitch": <true/false>,
    "mechanical_rhythm": <true/false>,
    "tts_artifacts": <true/false>,
    "unnatural_pacing": <true/false>
  }},
  "overall_assessment": {{
    "verdict": "authentic_human/likely_human/uncertain/likely_synthetic/synthetic_confirmed",
    "confidence_percentage": <0-100>,
    "risk_level": "low/medium/high",
    "recommendation": "approve/review_manually/flag_for_investigation"
  }},
  "detailed_observations": "comprehensive analysis",
  "samples_analyzed": {num_samples}
}}
```

**Scoring**: confidence_score 9-10=Very confident, 7-8=Confident, 5-6=Somewhat confident, 1-4=Low confidence

Provide ONLY JSON output."""
    
    @staticmethod
    def final_combined_analysis(transcript_text: str, resume_excerpt: str, job_role: str, session_id: str, candidate_name: str, candidate_email: str, buss_id: str, duration_sec: int, ended_early: bool, reconnections: int, background_persons: int) -> str:
        """Single prompt for the final combined JSON analysis."""
        return f"""You are an expert HR recruiter and technical evaluator.

**Context:**
- Session ID: {session_id}
- Candidate Name: {candidate_name}
- Candidate Email: {candidate_email}
- Buss ID: {buss_id}
- Job Role: {job_role}
- Duration (sec): {duration_sec}
- Ended Early: {str(ended_early).lower()}
- Reconnections: {reconnections}
- Background Persons Detected: {background_persons}

**Resume Context:**
{resume_excerpt}

**Raw Interview Transcript:**
{transcript_text}

**Your Task:**
Analyze the interview transcript and performance. Provide the output EXACTLY as the JSON schema below, and NOTHING ELSE.

```json
{{
  "session_id": "{session_id}",
  "candidate": {{
    "name": "{candidate_name}",
    "email": "{candidate_email}",
    "buss_id": "{buss_id}",
    "role": "{job_role}"
  }},
  "status": {{
    "completed": {"false" if ended_early else "true"},
    "ended_early": {str(ended_early).lower()},
    "duration_sec": {duration_sec}
  }},
  "scores": {{
    "overall": <float 1.0-5.0>,
    "technical": <float 1.0-5.0>,
    "communication": <float 1.0-5.0>,
    "behavioral": <float 1.0-5.0>,
    "authenticity": <float 1.0-5.0>
  }},
  "flags": [
    "<string, e.g., unable_to_explain_projects, ended_interview_early, etc.>"
  ],
  "summary": "<string: concise 2-3 sentence summary of the performance>",
  "recommendation": "<string: hire, reject, or review>",
  "transcript": [
    {{
      "turn": <int>,
      "speaker": "<string: assistant or candidate>",
      "timestamp": "<string: ISO 8601 or from transcript log>",
      "message": "<string: the message text>",
      "type": "<string: optional, e.g., security_check if it was a liveness spot check>"
    }}
  ],
  "metadata": {{
    "reconnections": {reconnections},
    "background_persons": {background_persons}
  }}
}}
```

**Instructions:**
- Parse the transcript text to reconstruct the `transcript` array exactly.
- Assign scores out of 5.0 based on the candidate's answers. If they could not answer technical questions, give a low technical score.
- Ensure the output is ONLY valid JSON.
"""

    @classmethod
    def get_prompt_metadata(cls) -> Dict[str, Any]:
        """Returns metadata about prompt templates."""
        return {
            "version": cls.VERSION,
            "templates": {
                "behavioral_screening": "Fairness-optimized screening analysis",
                "voice_authenticity": "Voice detection with forensic approach",
                "final_combined_analysis": "Final JSON combined schema output"
            }
        }
    
    @classmethod
    def validate_prompt_version(cls, required_version: str) -> bool:
        """Validates prompt template version compatibility."""
        return cls.VERSION >= required_version