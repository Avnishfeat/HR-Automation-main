# app/config/constants.py
from typing import Final

import os

class AudioConfig:
    # Sample Rates
    SAMPLE_RATE_24K: Final[int] = 24000  # Used for TTS/STT
    SAMPLE_RATE_48K: Final[int] = 48000  # Google Meet standard
    
    # Virtual Audio Device Names
    PLAYBACK_DEVICE_NAME: Final[str] = os.getenv("PLAYBACK_DEVICE_NAME", "BotSpeaker" if os.name != 'nt' else "CABLE Input")
    RECORDING_DEVICE_NAME: Final[str] = os.getenv("RECORDING_DEVICE_NAME", "BotMic.monitor" if os.name != 'nt' else "CABLE Output")
    
    # Audio Processing
    MIN_SPEECH_DURATION_SEC: Final[float] = 0.2  # Decreased to easily latch speech detection on short words
    VOLUME_THRESHOLD: Final[float] = 0.016         # Minimum volume to detect speech
    MAX_RECORDING_DURATION_SEC: Final[int] = 120  # Hard timeout for recording
    INITIAL_SPEECH_TIMEOUT_SEC: Final[float] = 12.0  # Stop waiting if candidate never starts
    TRANSCRIPT_IDLE_TIMEOUT_SEC: Final[float] = 1.8  # Stop after transcript/audio goes quiet
    
    # Simple fixed silence detection
    SILENCE_THRESHOLD_SEC: Final[float] = 1.5     # Increased to allow natural pauses
    MIN_RECORDING_SEC: Final[float] = 2.0         # Minimum recording time before silence can trigger

    # Audio Quality Checks
    MIN_AUDIO_DURATION_SEC: Final[float] = 1.0    # Minimum duration for valid audio
    MIN_VOLUME_THRESHOLD: Final[float] = 0.002    # Minimum average volume

class InterviewTiming:
    DEFAULT_DURATION_MINUTES: Final[int] = 10
    ESTIMATED_TURN_DURATION_SEC: Final[int] = 90  # For time remaining calculation
 
    CANDIDATE_JOIN_TIMEOUT_SEC: Final[int] = 900  # 15 minutes
    CANDIDATE_REJOIN_TIMEOUT_SEC: Final[int] = 120  # 2 minutes
    
    MAX_INTRO_ATTEMPTS: Final[int] = 2
    
    MIC_TOGGLE_DELAY_SEC: Final[float] = 0.1
    POST_PLAYBACK_DELAY_SEC: Final[float] = 0.5
    MEET_UI_SETTLE_DELAY_SEC: Final[int] = 3
    TRANSCRIPT_PROPAGATION_DELAY_SEC: Final[float] = 0.1

class VideoConfig:
    CAPTURE_INTERVAL_SEC: Final[int] = 5           # Time between snapshots
    INITIAL_WAIT_SEC: Final[int] = 5               # Wait before first capture
    MAX_CONSECUTIVE_FAILURES: Final[int] = 10      # Stop after this many failures
    JPEG_QUALITY: Final[int] = 90                  # Image quality
    
    REQUIRED_STABLE_CHECKS: Final[int] = 3         # Participant count must be stable
    STABILITY_CHECK_INTERVAL_SEC: Final[int] = 3   # Time between stability checks

class ResponseDetection:
    MAX_WORDS_FOR_STRICT_CHECK: Final[int] = 12

class ServiceConfig:
    GEMINI_TEMPERATURE: Final[float] = 0.0
    GEMINI_TOP_K: Final[int] = 1
    GEMINI_MODEL: Final[str] = "gemini-2.5-flash"
    GEMINI_TTS_MODEL: Final[str] = os.getenv(
        "GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview"
    )
    
    # TTS Configuration
    TTS_VOICE_LANGUAGE: Final[str] = "en-IN"
    # Gemini-TTS prebuilt voice. `en-IN` is supported by Gemini 3.1 Flash TTS.
    TTS_VOICE_NAME: Final[str] = os.getenv("GEMINI_TTS_VOICE", "Kore")
    # JSON object of text-to-pronunciation overrides applied before synthesis.
    TTS_PRONUNCIATION_OVERRIDES_JSON: Final[str] = os.getenv(
        "TTS_PRONUNCIATION_OVERRIDES_JSON", ""
    )
    TTS_MULAW_ENCODING: Final[str] = "MULAW"
    TTS_LINEAR16_ENCODING: Final[str] = "LINEAR16"
    
    # STT Configuration
    STT_LANGUAGE_CODE: Final[str] = "en-IN"
    STT_MODEL_V1: Final[str] = "default"
    STT_MODEL_V2: Final[str] = "chirp_3"
    STT_DEFAULT_REGION: Final[str] = "us"
    STT_VALID_REGIONS: Final[tuple] = ("us", "eu", "global")
    
    # gRPC Keep-Alive (for STT V2)
    GRPC_KEEPALIVE_TIME_MS: Final[int] = 30000
    GRPC_KEEPALIVE_TIMEOUT_MS: Final[int] = 10000
    GRPC_MAX_CHUNK_SIZE: Final[int] = 25600
    
    # Database
    DB_TIMEOUT_MS: Final[int] = 5000

class StoragePaths:
    DATA_ROOT: Final[str] = "data"
    CHROME_PROFILE_ROOT: Final[str] = "chrome_profile"
    STATIC_CACHE_ROOT: Final[str] = "data/static_cache"
    
    AUDIO_DIR: Final[str] = "audio"
    SNAPSHOTS_DIR: Final[str] = "captured_frames"
    TRANSCRIPTS_DIR: Final[str] = "transcripts"
    REPORTS_DIR: Final[str] = "reports"
    CAPTURED_IMAGES_DIR = "captured_frames"

class SessionStatus:
    PENDING: Final[str] = "pending"
    ACTIVE_SCHEDULED: Final[str] = "active_scheduled"
    ACTIVE_INTERVIEWING: Final[str] = "active_interviewing"
    ACTIVE_ANALYZING: Final[str] = "active_analyzing"
    CANDIDATE_JOINED: Final[str] = "candidate_joined"
    STOP_REQUESTED: Final[str] = "stop_requested"
    
    COMPLETED: Final[str] = "completed"
    COMPLETED_NO_ANALYSIS: Final[str] = "completed_no_analysis"
    TIME_LIMIT_REACHED: Final[str] = "time_limit_reached"
    INTERRUPTED: Final[str] = "interrupted"

    ERROR_CAPACITY_REACHED: Final[str] = "error_capacity_reached"
    ERROR_JOIN_FAILED: Final[str] = "error_join_failed"
    ERROR_CANDIDATE_NO_SHOW: Final[str] = "error_candidate_no_show"
    ERROR_CANDIDATE_LEFT: Final[str] = "error_candidate_left"
    ERROR_MULTIPLE_PARTICIPANTS: Final[str] = "error_multiple_participants"
    ERROR_ANALYSIS_EMPTY: Final[str] = "error_analysis_empty"
    ERROR_ANALYSIS_FAILED: Final[str] = "error_analysis_failed"
    ERROR_FATAL_TASK: Final[str] = "error_fatal_task"
    TERMINATED_LIVENESS_FAIL: Final[str] = "terminated_liveness_fail"
    
    ABORTED_MULTIPLE_PARTICIPANTS: Final[str] = "aborted_multiple_participants"
    ABORTED_MULTIPLE_PARTICIPANTS_TIMEOUT: Final[str] = "aborted_multiple_participants_timeout"

class TerminationReason:
    TIME_LIMIT_REACHED: Final[str] = "time_limit_reached"
    CANDIDATE_LEFT: Final[str] = "candidate_left"
    MULTIPLE_PARTICIPANTS: Final[str] = "multiple_participants"


class InterruptionReason:
    BACKEND_SHUTDOWN: Final[str] = "backend_shutdown"
    BACKEND_RESTARTED: Final[str] = "backend_restarted"

class StaticMessages:
    # Cache keys
    CACHE_KEY_INTRO_GREETING: Final[str] = "intro_greeting"
    CACHE_KEY_INTRO_REPROMPT: Final[str] = "intro_reprompt_generic"
    CACHE_KEY_ERROR_NO_RESPONSE: Final[str] = "error_no_response"
    CACHE_KEY_WARNING_EXIT: Final[str] = "warning_exit_attempt"
    CACHE_KEY_WARNING_MULTIPLE: Final[str] = "warning_multiple_people"
    CACHE_KEY_OUTRO_SUCCESS: Final[str] = "outro_success"
    CACHE_KEY_OUTRO_TIMEOUT: Final[str] = "outro_timeout"
    CACHE_KEY_OUTRO_FAILURE: Final[str] = "outro_failure"
    CACHE_KEY_WARNING_MULTIPLE = "warning_multiple_participants"
    
    # Message templates
    NO_RESPONSE: Final[str] = "Sorry, I didn't catch that. I'll repeat the question."
    EXIT_REDIRECT: Final[str] = "We still have a few more questions to cover. I'll repeat the last question for you."
    CACHE_KEY_EXIT_POLITE_CLOSE: Final[str] = "exit_polite_close"
    EXIT_POLITE_CLOSE: Final[str] = "Thank you for letting me know. I'll end the interview here, and the recruiting team can follow up about next steps."
    INTRO_REPROMPT: Final[str] = "Sorry, I didn't get that. Could you please introduce yourself?"
    RESUME_GREETING = "Welcome back. I paused the interview while you were away. Let's continue."
    CACHE_KEY_RESUME = "resume_greeting"
    OUTRO_MESSAGE = "Thank you for your time. We have gathered all the information we need. The recruiting team will be in touch with you soon. Have a great day!"
    CACHE_KEY_OUTRO = "outro_message"

class ErrorMessages:
    DELAY_APOLOGY: Final[str] = "One moment, I'm just organizing my notes."
    CONNECTION_GLITCH: Final[str] = "I apologize, I had a slight connection glitch. Let me ask that again."
    FALLBACK_REPHRASE: Final[str] = "I'm having trouble hearing you clearly. Could you please repeat that?"
    TECHNICAL_DIFFICULTIES_EXIT: Final[str] = (
        "I am terribly sorry, but we are experiencing significant technical difficulties "
        "that are affecting our conversation quality. "
        "To be respectful of your time, I will end the session now. "
        "Our recruiting team will reach out to reschedule. Thank you for your patience."
    )

class BrowserConfig:
    PAGE_LOAD_TIMEOUT_SEC: Final[int] = 60
    IMPLICIT_WAIT_SEC: Final[int] = 10
    ELEMENT_WAIT_TIMEOUT_SEC: Final[int] = 15
    HEADLESS: Final[bool] = True
    
    # Join button search
    JOIN_BUTTON_SEARCH_TIMEOUT_SEC: Final[int] = 60
    JOIN_BUTTON_CHECK_INTERVAL_SEC: Final[int] = 2
    
    # Post-join waits
    POST_JOIN_WAIT_SEC: Final[int] = 8
    POST_JOIN_VERIFY_TIMEOUT_SEC: Final[int] = 15

class LoggingConfig:
    SNAPSHOT_LOG_INTERVAL: Final[int] = 5  # Log every N snapshots
    PARTICIPANT_CHECK_LOG_INTERVAL_SEC: Final[int] = 5

class ParticipantThresholds:
    EXPECTED_COUNT: Final[int] = 2        # Bot + Candidate
    MIN_VALID_COUNT: Final[int] = 2       # Minimum for interview
    MAX_VALID_COUNT: Final[int] = 2       # Maximum allowed
    SINGLE_PARTICIPANT: Final[int] = 1    # Only bot (candidate left)
    REQUIRED_STABLE_CHECKS: Final[int] = 3

# HELPER FUNCTIONS
def get_audio_path_pattern(
    session_id: str,
    turn_count: int,
    is_follow_up: bool = False
) -> str:
    suffix = "_followup" if is_follow_up else ""
    return f"{StoragePaths.DATA_ROOT}/{session_id}/{StoragePaths.AUDIO_DIR}/candidate_turn_{turn_count}{suffix}_stt_24k.wav"


def get_snapshot_dir_path(session_id: str) -> str:
    return f"{StoragePaths.DATA_ROOT}/{session_id}/{StoragePaths.SNAPSHOTS_DIR}"


def get_transcript_path(session_id: str) -> str:
    return f"{StoragePaths.DATA_ROOT}/{session_id}/transcript.txt"


def get_report_path(session_id: str) -> str:
    return f"{StoragePaths.DATA_ROOT}/{session_id}/{StoragePaths.REPORTS_DIR}/final_screening_report.json"
