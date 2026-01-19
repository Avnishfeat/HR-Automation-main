# app/config/settings.py
# Bridge settings from app.core.config

from app.core.config import settings

class Config:
    """Bridge class to maintain backward compatibility with interview bot."""
    
    # Database
    MONGODB_URL = settings.MONGODB_URL
    DATABASE_NAME = settings.DATABASE_NAME
    
    # Google Cloud
    GOOGLE_CLOUD_PROJECT = settings.GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION = settings.GOOGLE_CLOUD_LOCATION
    GOOGLE_APPLICATION_CREDENTIALS = settings.GOOGLE_APPLICATION_CREDENTIALS
    SPEECH_API_VERSION = settings.SPEECH_API_VERSION
    
    # Gemini
    GEMINI_API_KEY = settings.GEMINI_API_KEY
    GENAI_MODEL = settings.GENAI_MODEL
    
    # Chrome/Selenium
    CHROME_PROFILE_PATH = settings.CHROME_PROFILE_PATH
    HEADLESS_MODE = settings.HEADLESS_MODE
    
    # Interview Settings
    MAX_CONCURRENT_INTERVIEWS = settings.MAX_CONCURRENT_INTERVIEWS
    DEFAULT_INTERVIEW_DURATION_MINUTES = settings.DEFAULT_INTERVIEW_DURATION_MINUTES
