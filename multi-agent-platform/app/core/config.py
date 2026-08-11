from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Multi-Agent Platform"
    APP_VERSION: str = "1.0.0"
    APP_PORT: int = 8048
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    
    GENAI_MODEL: str = "gemini-2.5-flash"
    # LLM API Keys
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    # File Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    # CORS
    ALLOWED_ORIGINS: list = ["*"]

    # --- Interview Bot Settings ---
    GOOGLE_CLOUD_PROJECT: Optional[str] = None
    GOOGLE_CLOUD_LOCATION: str = "us-central1"
    GOOGLE_CLOUD_REGION: str = "us"
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    SPEECH_API_VERSION: str = "v2"
    DATABASE_URL: Optional[str] = None
    DATABASE_CONNECT_TIMEOUT_SEC: int = 5
    IDEMPOTENCY_KEY_RETENTION_DAYS: int = 90
    INTERVIEW_RECORD_RETENTION_DAYS: int = 90
    
    # Browser Settings
    CHROME_PROFILE_PATH: str = "./chrome_profile"
    HEADLESS_MODE: bool = False
    
    # Interview Settings
    MAX_CONCURRENT_INTERVIEWS: int = 5
    DEFAULT_INTERVIEW_DURATION_MINUTES: int = 30
    
    @field_validator("DEBUG", "HEADLESS_MODE", mode="before")
    @classmethod
    def parse_boolish(cls, value: Any) -> Any:
        if isinstance(value, bool) or value is None:
            return value

        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False

        return value

    @field_validator("SPEECH_API_VERSION", mode="before")
    @classmethod
    def normalize_speech_api_version(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("GOOGLE_CLOUD_REGION", mode="before")
    @classmethod
    def normalize_google_cloud_region(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        valid_regions = {"us", "eu", "global"}
        return normalized if normalized in valid_regions else "us"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
