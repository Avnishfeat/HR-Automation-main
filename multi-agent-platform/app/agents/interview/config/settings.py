# app/config/settings.py
"""
Application Configuration Management
Centralizes environment variables and validates settings on startup.
"""

import os
import logging
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables first (before importing secrets)
load_dotenv()

# Import centralized secrets manager
from app.agents.interview.config.secrets import secrets, SecretsManager

logger = logging.getLogger(__name__)


class Config:
    """Application configuration with centralized secrets management."""
    
    # Non-secret configuration (safe to log)
    ENV: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    SPEECH_API_VERSION: str = os.getenv("SPEECH_API_VERSION", "v2").lower()
    GOOGLE_CLOUD_REGION: str = os.getenv("GOOGLE_CLOUD_REGION", "us")
    
    # Paths (non-secret)
    DATA_ROOT: Path = Path("data")
    CHROME_PROFILE_PATH: Path = Path("chrome_profile").resolve()
    STATIC_CACHE_PATH: Path = DATA_ROOT / "static_cache"
    
    # Secrets - accessed via SecretsManager (never stored as class attributes)
    @classmethod
    def get_gemini_api_key(cls) -> Optional[str]:
        """Get Gemini API key from secrets manager."""
        return secrets.get("GEMINI_API_KEY")
    
    @classmethod
    def get_mongodb_url(cls) -> Optional[str]:
        """Get MongoDB URL from secrets manager."""
        return secrets.get("MONGODB_URL")
    
    @classmethod
    def get_google_cloud_project(cls) -> Optional[str]:
        """Get Google Cloud project from secrets manager."""
        return secrets.get("GOOGLE_CLOUD_PROJECT")
    
    @classmethod
    def get_google_credentials_path(cls) -> Optional[str]:
        """Get Google Application Credentials path from secrets manager."""
        return secrets.get("GOOGLE_APPLICATION_CREDENTIALS")
    
    
    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """Validate configuration using secrets manager."""
        errors = []
        
        # Validate secrets using centralized SecretsManager
        secrets_valid, secrets_errors = secrets.validate_all()
        errors.extend(secrets_errors)
        
        # Check Google Cloud (warning only - not required)
        if not cls.get_google_cloud_project():
            logger.warning("GOOGLE_CLOUD_PROJECT not set - STT V2 will not work")
        
        # Check Speech API version
        if cls.SPEECH_API_VERSION not in ["v1", "v2"]:
            errors.append(f"Invalid SPEECH_API_VERSION: {cls.SPEECH_API_VERSION}. Must be 'v1' or 'v2'")
        
        # Check Google Cloud region
        valid_regions = ["us", "eu", "global"]
        if cls.GOOGLE_CLOUD_REGION not in valid_regions:
            logger.warning(
                f"Invalid GOOGLE_CLOUD_REGION '{cls.GOOGLE_CLOUD_REGION}'. "
                f"Valid options: {valid_regions}. Defaulting to 'us'."
            )
            cls.GOOGLE_CLOUD_REGION = "us"
        
        return len(errors) == 0, errors
    
    @classmethod
    def setup_directories(cls):
        """Create necessary directories if they don't exist."""
        directories = [
            cls.DATA_ROOT,
            cls.CHROME_PROFILE_PATH,
            cls.STATIC_CACHE_PATH
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")
    
    @classmethod
    def log_configuration(cls):
        """Log current configuration (secrets are masked for safety)."""
        logger.info("="*60)
        logger.info("APPLICATION CONFIGURATION")
        logger.info("="*60)
        logger.info(f"Environment: {cls.ENV}")
        logger.info(f"Debug Mode: {cls.DEBUG}")
        logger.info(f"Speech API Version: {cls.SPEECH_API_VERSION}")
        logger.info(f"Google Cloud Region: {cls.GOOGLE_CLOUD_REGION}")
        logger.info(f"Data Root: {cls.DATA_ROOT}")
        logger.info(f"Chrome Profile: {cls.CHROME_PROFILE_PATH}")
        
        # Log secrets health (masked) - never log actual values
        logger.info("--- Secrets Status ---")
        secrets_health = secrets.health_check()
        for secret_name, status in secrets_health.items():
            status_str = "✓ SET" if status["set"] else "✗ NOT SET"
            required_str = "(required)" if status["required"] else "(optional)"
            logger.info(f"  {secret_name}: {status_str} {required_str}")
        logger.info("="*60)
    
    @classmethod
    def initialize(cls):
        # Validate configuration
        is_valid, errors = cls.validate()
        
        if not is_valid:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Setup directories
        cls.setup_directories()
        
        # Log configuration
        cls.log_configuration()
        
        logger.info(" Configuration initialized successfully")



# CONVENIENCE ACCESSORS

def get_config() -> type[Config]:
    return Config


def validate_config() -> bool:
    is_valid, errors = Config.validate()
    if not is_valid:
        for error in errors:
            logger.error(f"Config Error: {error}")
    return is_valid


# =============================================================================
# AUTO-INITIALIZE ON IMPORT (Optional)
# =============================================================================

# Uncomment this if you want automatic initialization when config is imported
# try:
#     Config.initialize()
# except Exception as e:
#     logger.critical(f"Failed to initialize configuration: {e}")
#     raise