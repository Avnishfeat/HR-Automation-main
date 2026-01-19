from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

class SessionRepository(ABC):
    @abstractmethod
    async def create_session(self, session_data: Dict) -> str:
        """Create a new session and return its ID"""
        pass
    
    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session by ID"""
        pass
    
    @abstractmethod
    async def update_session(self, session_id: str, updates: Dict) -> bool:
        """Update session fields"""
        pass
    
    @abstractmethod
    async def update_session_status(self, session_id: str, status: str) -> bool:
        """Update just the status field"""
        pass
    
    @abstractmethod
    async def add_turn(self, session_id: str, turn_data: Dict) -> bool:
        """Add a conversation turn to the session"""
        pass
    
    @abstractmethod
    async def get_active_sessions(self) -> List[Dict]:
        """Get all currently active sessions"""
        pass
