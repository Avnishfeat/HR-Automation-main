import logging
from pathlib import Path
from typing import Optional

from app.agents.interview.config.secrets import SecretsManager, secrets
from app.core.config import settings

logger = logging.getLogger(__name__)


class Config:
    """Compatibility wrapper backed by the canonical core settings object."""

    ENV: str = settings.ENVIRONMENT
    DEBUG: bool = settings.DEBUG
    GOOGLE_CLOUD_PROJECT: Optional[str] = settings.GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION: str = settings.GOOGLE_CLOUD_LOCATION
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = settings.GOOGLE_APPLICATION_CREDENTIALS
    SPEECH_API_VERSION: str = settings.SPEECH_API_VERSION
    GOOGLE_CLOUD_REGION: str = settings.GOOGLE_CLOUD_REGION
    GEMINI_API_KEY: Optional[str] = settings.GEMINI_API_KEY
    GENAI_MODEL: str = settings.GENAI_MODEL
    HEADLESS_MODE: bool = settings.HEADLESS_MODE
    MAX_CONCURRENT_INTERVIEWS: int = settings.MAX_CONCURRENT_INTERVIEWS
    DEFAULT_INTERVIEW_DURATION_MINUTES: int = settings.DEFAULT_INTERVIEW_DURATION_MINUTES

    DATA_ROOT: Path = Path("data")
    CHROME_PROFILE_PATH: Path = Path(settings.CHROME_PROFILE_PATH).resolve()
    STATIC_CACHE_PATH: Path = DATA_ROOT / "static_cache"

    @classmethod
    def get_gemini_api_key(cls) -> Optional[str]:
        return secrets.get("GEMINI_API_KEY")

    @classmethod
    def get_google_cloud_project(cls) -> Optional[str]:
        return settings.GOOGLE_CLOUD_PROJECT

    @classmethod
    def get_google_credentials_path(cls) -> Optional[str]:
        return settings.GOOGLE_APPLICATION_CREDENTIALS

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        errors: list[str] = []

        _, secret_errors = secrets.validate_all()
        errors.extend(secret_errors)

        if not cls.get_google_cloud_project():
            logger.warning("GOOGLE_CLOUD_PROJECT not set - STT V2 will not work")

        if cls.SPEECH_API_VERSION not in {"v1", "v2"}:
            errors.append(
                f"Invalid SPEECH_API_VERSION: {cls.SPEECH_API_VERSION}. Must be 'v1' or 'v2'"
            )

        if cls.GOOGLE_CLOUD_REGION not in {"us", "eu", "global"}:
            logger.warning(
                "Invalid GOOGLE_CLOUD_REGION '%s'. Valid options: ['us', 'eu', 'global']. Defaulting to 'us'.",
                cls.GOOGLE_CLOUD_REGION,
            )
            cls.GOOGLE_CLOUD_REGION = "us"

        return len(errors) == 0, errors

    @classmethod
    def setup_directories(cls) -> None:
        for directory in [cls.DATA_ROOT, cls.CHROME_PROFILE_PATH, cls.STATIC_CACHE_PATH]:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug("Ensured directory exists: %s", directory)

    @classmethod
    def log_configuration(cls) -> None:
        logger.info("=" * 60)
        logger.info("APPLICATION CONFIGURATION")
        logger.info("=" * 60)
        logger.info("Environment: %s", cls.ENV)
        logger.info("Debug Mode: %s", cls.DEBUG)
        logger.info("Speech API Version: %s", cls.SPEECH_API_VERSION)
        logger.info("Google Cloud Region: %s", cls.GOOGLE_CLOUD_REGION)
        logger.info("Data Root: %s", cls.DATA_ROOT)
        logger.info("Chrome Profile: %s", cls.CHROME_PROFILE_PATH)
        logger.info("--- Secrets Status ---")

        for secret_name, status in secrets.health_check().items():
            status_str = "SET" if status["set"] else "NOT SET"
            required_str = "(required)" if status["required"] else "(optional)"
            logger.info("  %s: %s %s", secret_name, status_str, required_str)

        logger.info("=" * 60)

    @classmethod
    def initialize(cls) -> None:
        is_valid, errors = cls.validate()
        if not is_valid:
            error_msg = "Configuration validation failed:\n" + "\n".join(
                f"  - {err}" for err in errors
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        cls.setup_directories()
        cls.log_configuration()
        logger.info("Configuration initialized successfully")


def get_config() -> type[Config]:
    return Config


def validate_config() -> bool:
    is_valid, errors = Config.validate()
    if not is_valid:
        for error in errors:
            logger.error("Config Error: %s", error)
    return is_valid


__all__ = ["Config", "SecretsManager", "get_config", "secrets", "validate_config"]