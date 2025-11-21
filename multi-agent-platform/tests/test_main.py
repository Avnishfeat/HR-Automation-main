# File: tests/test_main.py

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from unittest.mock import patch, AsyncMock
from app.main import app
from app.core.dependencies import get_llm_service

def test_root_endpoint(api_client: TestClient):
    """Tests the root / endpoint."""
    response = api_client.get("/")
    assert response.status_code == 200
    assert "Multi-Agent Platform API" in response.json()["message"]

@pytest.mark.asyncio
async def test_websocket_endpoint(api_client: TestClient):
    """Tests the WebSocket /ws/{client_id} endpoint."""
    client_id = "test-ws-client"
    
    try:
        with api_client.websocket_connect(f"/ws/{client_id}") as websocket:
            websocket.send_text("Hello")
            data = websocket.receive_text()
            assert data == "Echo: Hello"
            
    except WebSocketDisconnect:
        pass # Expected on close

def test_lifespan_startup_failure(mock_llm_service):
    """
    Tests that the app fails to start if the database connection fails.
    Covers the 'except' block in the lifespan manager.
    """
    # Override dependency *before* creating the TestClient
    app.dependency_overrides[get_llm_service] = lambda: mock_llm_service
    
    # Patch the connect_db method to raise an error
    with patch("app.services.database.DatabaseService.connect_db", 
               new_callable=AsyncMock, 
               side_effect=Exception("DB Connection Failed")):
        
        # Starting the TestClient will trigger the lifespan startup
        with pytest.raises(Exception, match="DB Connection Failed"):
            with TestClient(app) as client:
                pass # The error happens on startup
    
    # Clean up overrides
    app.dependency_overrides.clear()