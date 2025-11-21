# File: tests/core/test_dependencies.py

from app.core.dependencies import (
    get_llm_service, # Added
    get_db_service, 
    get_file_service, 
    get_websocket_manager,
    llm_service, # Added
    db_service,
    file_service,
    websocket_manager
)
from app.services.llm_service import LLMService # Added
from app.services.database import DatabaseService
from app.services.file_service import FileService
from app.services.websocket_manager import WebSocketManager

def test_get_llm_service():
    """
    Tests that the getter returns the singleton instance.
    Covers the get_llm_service function.
    """
    service = get_llm_service()
    assert isinstance(service, LLMService)
    assert service is llm_service # Check it's the singleton

def test_get_db_service():
    """Tests that the getter returns the singleton instance."""
    service = get_db_service()
    assert isinstance(service, DatabaseService)
    assert service is db_service

def test_get_file_service():
    """Tests that the getter returns the singleton instance."""
    service = get_file_service()
    assert isinstance(service, FileService)
    assert service is file_service

def test_get_websocket_manager():
    """Tests that the getter returns the singleton instance."""
    service = get_websocket_manager()
    assert isinstance(service, WebSocketManager)
    assert service is websocket_manager