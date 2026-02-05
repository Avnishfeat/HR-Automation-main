# app/core/security.py

from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Union
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

# 1. Setup Password Hashing
# We use bcrypt, which is slow by design to resist brute-force attacks.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Checks if the raw password matches the stored hash.
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    # Scrambles the password into a secure hash.
    return pwd_context.hash(password)


# 2. Setup JWT Generation
def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    #Creates a JWT token containing the user's ID (subject).

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Default fallback if no specific time is requested
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # The "payload" is the data hidden inside the token
    to_encode = {
        "sub": str(subject),      # 'sub' is standard for 'subject' (User ID/Username)
        "exp": expire             # 'exp' tells the server when this token dies
    }
    
    # Sign the token using our SECRET_KEY
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt