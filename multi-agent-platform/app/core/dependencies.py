from app.services.llm_service import LLMService, GeminiProvider, OpenAIProvider
from app.services.database import DatabaseService
from app.services.file_service import FileService
from app.services.websocket_manager import WebSocketManager
from app.core.config import settings

# Singleton instances
_llm_service = None
_file_service = None
_websocket_manager = None

def get_llm_service() -> LLMService:
    """Dependency for LLM Service"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
        
        # Register providers
        if settings.GEMINI_API_KEY:
            _llm_service.register_provider(
                "gemini", 
                GeminiProvider(settings.GEMINI_API_KEY)
            )
        
        if settings.OPENAI_API_KEY:
            _llm_service.register_provider(
                "openai", 
                OpenAIProvider(settings.OPENAI_API_KEY)
            )
    
    return _llm_service

def get_db_service() -> DatabaseService:
    """Dependency for Database Service"""
    return DatabaseService

def get_file_service() -> FileService:
    """Dependency for File Service"""
    global _file_service
    if _file_service is None:
        _file_service = FileService(settings.UPLOAD_DIR)
    return _file_service

def get_websocket_manager() -> WebSocketManager:
    """Dependency for WebSocket Manager"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
