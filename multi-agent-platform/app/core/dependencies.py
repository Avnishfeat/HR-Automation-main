# app/core/dependencies.py

# --- Application-Specific Imports ---
from app.core.config import settings
from app.services.llm_service import LLMService
from app.services.database import DatabaseService
from app.services.file_service import FileService
from app.services.websocket_manager import WebSocketManager
# NOTE: You may need to add imports for your provider classes if they are in a separate file
# from app.services.llm_providers import GeminiProvider, OpenAIProvider


# --- Create Singleton Instances ---
# We create a single, shared instance of each service when the app starts.
# This is a clean, simple, and thread-safe approach.
llm_service = LLMService(settings)
db_service = DatabaseService()
file_service = FileService(settings.UPLOAD_DIR)
websocket_manager = WebSocketManager()


# --- Dependency Getter Functions ---
# The dependency functions are now simple one-liners that just return the instance.

def get_llm_service() -> LLMService:
    """Dependency injector that provides the singleton LLMService instance."""
    return llm_service

def get_db_service() -> DatabaseService:
    """Dependency injector that provides the singleton DatabaseService instance."""
    return db_service

def get_file_service() -> FileService:
    """Dependency injector that provides the singleton FileService instance."""
    return file_service

def get_websocket_manager() -> WebSocketManager:
    """Dependency injector that provides the singleton WebSocketManager instance."""
    return websocket_manager