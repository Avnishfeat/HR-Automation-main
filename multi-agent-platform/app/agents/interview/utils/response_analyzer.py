# app/utils/response_analyzer.py
import logging
import re  # Import the regular expression module
from typing import Tuple

logger = logging.getLogger(__name__)

# --- Non-committal Detection ---

_non_committal_phrases = [
    "i don't know", "i do not know", "no idea", "not sure",
    "i'm not sure", "i am confused", "cant answer", "no clue"
]
_non_committal_pattern = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _non_committal_phrases) + r")\b",
    re.IGNORECASE
)

def detect_non_committal_response(transcript: str) -> bool:
    """Detects non-committal phrases using whole-word matching."""
    if not transcript:
        return False
    return _non_committal_pattern.search(transcript) is not None

# --- Repeat Request Detection (Handles Non-Answers) ---

# We must treat "sorry" as a special case.
# First, list all the phrases that are NOT "sorry":
_repeat_phrases_normal = [
    "repeat the question", "repeat that", "say that again",
    "could you repeat", "pardon", "didn't hear", "did not hear",
    "sorry what", "sorry can you", "didn't catch", "could you say",
    "come again", "one more time"
]

# 1. Create a pattern for all the normal phrases
pattern_normal = r"\b(" + "|".join(re.escape(p) for p in _repeat_phrases_normal) + r")\b"

# 2. Create a special pattern for "sorry"
# (?<!...) is a "Negative Lookbehind".
# It must be FIXED-WIDTH. We use \s (exactly one space) instead of \s*
# This matches \bsorry\b ONLY IF it is NOT preceded by "not " or "n't ".
# Both 'not\s' and 'n\'t\s' are exactly 4 characters, so this is valid.
pattern_sorry = r"(?<!not\s|n't\s)\bsorry\b"

# 3. Combine both patterns with an OR (|)
_repeat_pattern = re.compile(
    f"({pattern_normal}|{pattern_sorry})",  # Combine the two patterns
    re.IGNORECASE
)

def detect_repeat_request(transcript: str) -> bool:
    """
    Detects repeat request phrases (non-answers) using whole-word matching.
    """
    if not transcript:
        return False
    
    # This will now match "Sorry, I missed that"
    # but will NOT match "I am not sorry"
    
    # We also check word count to avoid false positives on long answers
    # that might happen to contain a keyword.
    transcript_clean = transcript.lower().strip()
    word_count = len(transcript_clean.split())

    # Only apply strict check if the response is relatively short
    if word_count <= 12:
        if _repeat_pattern.search(transcript):
            # Check for common content words to AVOID classifying as a repeat request
            content_indicators = [
                "project", "experience", "worked", "used", "developed",
                "implemented", "designed", "built", "created", "system",
                "application", "feature", "code", "data", "team", "years"
            ]
            has_content = any(indicator in transcript_clean for indicator in content_indicators)
            
            if not has_content:
                logger.debug(f"Repeat request detected: '{transcript}'")
                return True
    
    return False


# --- Exit Intent Detection ---

# More specific exit keywords (complete phrases only)
_exit_keywords = [
    # Meeting end phrases
    "end the meeting", "end this meeting", "end the interview", "end this interview",
    
    # Leave phrases with intent
    "i want to leave", "i need to leave", "i have to leave", "i'm going to leave",
    "i am going to leave", "can i leave", "may i leave", "let me leave",
    
    # Stop phrases
    "stop the interview", "stop this interview", "i want to stop", "i need to stop",
    
    # Call-specific
    "leave the call", "exit the call", "quit the call",
    
    # General end with context
    "can we end", "i want to end", "let's end"
]

# Pre-compile regex patterns for exit intents
_exit_phrase_patterns = [
    re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
    for keyword in _exit_keywords
]

_exit_verbs = ["leave", "quit", "exit", "stop", "end"]
_intent_words = ["want to", "going to", "need to", "have to", "can i", "may i", "let me"]

_exit_combo_patterns = []
for verb in _exit_verbs:
    for intent in _intent_words:
        # Match intent...verb with up to 3 intervening words
        pattern_str = r'\b' + re.escape(intent) + r'\s+(\w+\s+){0,3}' + re.escape(verb) + r'\b'
        _exit_combo_patterns.append((re.compile(pattern_str, re.IGNORECASE), f"{intent}...{verb}"))


def detect_exit_intent(transcript: str) -> Tuple[bool, str]:
    """
    Check if transcript contains an intent to exit the interview.
    Returns (bool_detected, matched_keyword_or_pattern)
    """
    if not transcript:
        return False, ""
        
    transcript_lower = transcript.lower()
    
    # Check specific complete phrases first
    for i, pattern in enumerate(_exit_phrase_patterns):
        if pattern.search(transcript_lower):
            keyword = _exit_keywords[i]
            logger.info(f"🚪 Exit intent detected with phrase: '{keyword}'")
            return True, keyword
    
    # Check intent combinations
    for pattern, combined_key in _exit_combo_patterns:
        if pattern.search(transcript_lower):
            logger.info(f"🚪 Exit intent detected with pattern: '{combined_key}'")
            return True, combined_key
    
    return False, ""

_clarification_phrases = [
    # Name/identity questions
    "what is my name", "what's my name", "who am i", "do you know my name",
    
    # Camera/mic questions
    "camera on", "camera off", "should i keep camera", "turn on camera",
    "microphone on", "mic on", "should i enable",
    
    # Interview process questions
    "how long", "how many questions", "when will this end", "how much time",
    "what happens next", "what should i do",
    
    # Clarification requests
    "what do you mean", "can you clarify", "i don't understand the question",
    "what are you asking", "could you explain"
]

_clarification_pattern = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _clarification_phrases) + r")",
    re.IGNORECASE
)

def detect_clarification_request(transcript: str) -> Tuple[bool, str]:
    """
    Detects if the user is asking for clarification about the interview process.
    Returns (bool_detected, matched_phrase)
    """
    if not transcript:
        return False, ""
    
    match = _clarification_pattern.search(transcript.lower())
    if match:
        logger.info(f"Clarification request detected: '{match.group(0)}'")
        return True, match.group(0)
    
    return False, ""