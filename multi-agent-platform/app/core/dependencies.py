# app/core/dependencies.py
# Standard Library Imports
from typing import Annotated

# Third-Party Imports
from fastapi import HTTPException, status, Request, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

# Application-Specific Imports 
from app.core.config import settings
from app.services.llm_service import LLMService
from app.services.database import DatabaseService
from app.services.file_service import FileService
from app.services.websocket_manager import WebSocketManager
from app.services.user_service import UserService
from app.models.user import UserInDB

# --- Create Singleton Instances ---
llm_service = LLMService(settings)
db_service = DatabaseService()
file_service = FileService(settings.UPLOAD_DIR)
websocket_manager = WebSocketManager()

# Validates the JWT token and retrieves the user. 
# If anything is wrong (expired, fake, user deleted), it raises 401.
async def get_current_user(request: Request) -> UserInDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    
    # 1. Extract Token from COOKIE (not header)
    token = request.cookies.get("access_token")
    if not token:
        raise credentials_exception
    
    try:
        # 2. Decode Token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
    
    # 3. Verify User exists in DB
    user_service = UserService()
    user = await user_service.get_user_by_email(email)
    
    if user is None:
        raise credentials_exception
        
    return user
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