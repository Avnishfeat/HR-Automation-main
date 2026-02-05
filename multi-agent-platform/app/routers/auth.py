from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.core import security
from app.core.config import settings
from app.models.user import UserCreate, UserResponse, UserInDB
from app.services.user_service import UserService
from app.models.user import LoginRequest

router = APIRouter()
user_service = UserService()

# 1. REGISTER ENDPOINT
@router.post("/signup", response_model=UserResponse)
async def create_user(user: UserCreate):
    # 1. Application-Level Check (Fast Feedback)
    existing_user = await user_service.get_user_by_email(user.email)
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already exists" # <--- Updated message
        )
    # 2. Hash Password
    hashed_pw = security.get_password_hash(user.password)

    # 3. Create DB Object
    # Since UserCreate now has full_name and organization_name,
    # user.model_dump() will pass them to UserInDB automatically.
    user_in_db = UserInDB(
        **user.model_dump(exclude={"password"}), 
        hashed_password=hashed_pw,
        disabled=False
    )
    try:
        await user_service.create_user(user_in_db)
    except ValueError as e:
        # Catches the error raised by create_user if DuplicateKeyError happens
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )
        
    return user_in_db

@router.post("/login")
async def login(response: Response, login_data: LoginRequest):
    """
    Login that sets a secure HttpOnly cookie.
    """
    # 1. Verify User
    user = await user_service.get_user_by_email(login_data.email)
    if not user or not security.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # 2. Create Token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        subject=user.email,
        expires_delta=access_token_expires
    )

    # 3. Set the Cookie
    # We strip the "Bearer " prefix for cookies; we just store the raw token string.
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,   # <--- The magic security flag
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",  # Protects against CSRF
        secure=False     
    )

    # 4. Return success message (Token is NOT in the body anymore)
    return {
        "status": "active",
        "message": "Login successful",
    }

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}