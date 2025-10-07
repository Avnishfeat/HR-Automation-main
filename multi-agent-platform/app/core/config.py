from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Consolidated configuration class for the application.
    Loads settings from a .env file and environment variables.
    """
    # --- App Settings ---
    APP_NAME: str = "Multi-Agent Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # --- Database ---
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "multi_agent_db"
    
    # --- LLM API Keys and Models ---
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    # This field is now correctly defined to load from your .env file.
    # It defaults to a valid model name if not specified.
    GENAI_MODEL: str = "models/gemini-2.5-pro"  # <-- CHANGED: Default model name
    
    # --- File Upload ---
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    # This is the specific temporary directory for the interview analysis agent.
    TEMP_DIR: Path = Path("temp_audio")
    
    # --- CORS ---
    ALLOWED_ORIGINS: List[str] = ["*"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        # This will prevent crashes if other extra variables are in the .env
        extra = 'ignore' 

# --- Instantiation and Setup ---
# The settings object is created only ONCE from the correct class definition.
settings = Settings()

# Ensure the temporary directory exists after the settings are loaded.
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)

