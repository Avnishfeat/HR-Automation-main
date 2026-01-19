# app/config/secrets.py
# Bridge secrets from app.core.config

from app.core.config import settings

class secrets:
    """Bridge class to maintain backward compatibility with interview bot."""
    
    GEMINI_API_KEY = settings.GEMINI_API_KEY
    MONGODB_URL = settings.MONGODB_URL
    GOOGLE_CLOUD_PROJECT = settings.GOOGLE_CLOUD_PROJECT
    GOOGLE_APPLICATION_CREDENTIALS = settings.GOOGLE_APPLICATION_CREDENTIALS
