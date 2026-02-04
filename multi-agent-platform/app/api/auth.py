from fastapi import APIRouter, status
from app.models.user import UserCreate, UserResponse
from app.services.auth_service import AuthService

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate):
    """
    Register a new user.
    """
    user = await AuthService.create_user(user_in)
    
    # Manually map to response since UserResponse expects id but UserInDB doesn't rely on it being set immediately 
    # (Mongo ID handling can be tricky with Pydantic v2, we'll return basic info for now)
    return UserResponse(
        id=user.email,  # Using email as ID for response simplicity or mapped actual ID if available
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at
    )
