# File: tests/services/test_websocket_manager.py

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from app.services.websocket_manager import WebSocketManager

@pytest.mark.asyncio
async def test_connect_second_client():
    """
    Tests that connecting a second websocket to the same client_id
    adds it to the existing list.
    Covers the 'else' path of 'if client_id not in...'.
    """
    manager = WebSocketManager()
    mock_ws_1 = AsyncMock()
    mock_ws_2 = AsyncMock()
    client_id = "client-1"
    
    await manager.connect(mock_ws_1, client_id)
    assert len(manager.active_connections[client_id]) == 1
    
    # Connect second client
    await manager.connect(mock_ws_2, client_id)
    assert len(manager.active_connections[client_id]) == 2
    assert manager.active_connections[client_id] == [mock_ws_1, mock_ws_2]

@pytest.mark.asyncio
async def test_disconnect_last_client():
    """
    Tests that disconnecting the last client for a client_id
    correctly removes the client_id key.
    """
    manager = WebSocketManager()
    mock_ws = AsyncMock()
    client_id = "client-1"
    
    await manager.connect(mock_ws, client_id)
    assert client_id in manager.active_connections
    
    manager.disconnect(mock_ws, client_id)
    assert client_id not in manager.active_connections

def test_disconnect_non_existent(caplog):
    """
    Tests that disconnecting a client_id that doesn't exist runs
    without error. Covers the 'if client_id in...' (False) path.
    """
    manager = WebSocketManager()
    mock_ws = AsyncMock()
    
    # This should not raise an error
    manager.disconnect(mock_ws, "non-existent-client")
    assert "non-existent-client" not in manager.active_connections

@pytest.mark.asyncio
async def test_broadcast():
    """
    Tests that broadcast sends a message to all connected clients.
    Covers the `broadcast` method.
    """
    manager = WebSocketManager()
    
    mock_ws_1 = AsyncMock()
    mock_ws_2a = AsyncMock()
    mock_ws_2b = AsyncMock()
    
    await manager.connect(mock_ws_1, "client-1")
    await manager.connect(mock_ws_2a, "client-2")
    await manager.connect(mock_ws_2b, "client-2")
    
    await manager.broadcast("Hello all")
    
    mock_ws_1.send_text.assert_called_once_with("Hello all")
    mock_ws_2a.send_text.assert_called_once_with("Hello all")
    mock_ws_2b.send_text.assert_called_once_with("Hello all")