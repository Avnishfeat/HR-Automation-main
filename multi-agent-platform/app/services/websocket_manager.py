from fastapi import WebSocket
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class WebSocketManager:
    """WebSocket connection manager"""
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept and store WebSocket connection"""
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = []
        self.active_connections[client_id].append(websocket)
        logger.info(f"🔌 Client {client_id} connected")
    
    def disconnect(self, websocket: WebSocket, client_id: str):
        """Remove WebSocket connection"""
        if client_id in self.active_connections:
            self.active_connections[client_id].remove(websocket)
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]
        logger.info(f"🔌 Client {client_id} disconnected")
    
    async def send_message(self, message: str, client_id: str):
        """Send message to specific client"""
        if client_id in self.active_connections:
            for connection in self.active_connections[client_id]:
                await connection.send_text(message)
    
    async def broadcast(self, message: str):
        """Broadcast message to all connected clients"""
        for client_connections in self.active_connections.values():
            for connection in client_connections:
                await connection.send_text(message)
