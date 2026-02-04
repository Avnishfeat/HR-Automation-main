from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Multi-Agent Platform"
    APP_VERSION: str = "1.0.0"
    APP_PORT: int = 5649
    DEBUG: bool = True
    
    # Database
    MONGODB_URL: str
    DATABASE_NAME: str
    
    GENAI_MODEL: str = "gemini-2.5-flash"
    # LLM API Keys
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    # File Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    # CORS
    ALLOWED_ORIGINS: list = ["*"]

    # --- Security ---
    SECRET_KEY: str = "your-super-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # --- Interview Bot Settings ---
    GOOGLE_CLOUD_PROJECT: Optional[str] = None
    GOOGLE_CLOUD_LOCATION: str = "us-central1"
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    SPEECH_API_VERSION: str = "v2"
    
    # Chrome/Selenium Settings
    CHROME_PROFILE_PATH: str = "./chrome_profile"
    HEADLESS_MODE: bool = False
    
    # Interview Settings
    MAX_CONCURRENT_INTERVIEWS: int = 5
    DEFAULT_INTERVIEW_DURATION_MINUTES: int = 30
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()