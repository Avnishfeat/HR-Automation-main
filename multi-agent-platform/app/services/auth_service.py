from datetime import datetime
import logging
from fastapi import HTTPException, status
from pymongo.collection import Collection

from app.core.security import get_password_hash
from app.models.user import UserCreate, UserInDB
from app.services.database import DatabaseService
from app.core.config import settings

logger = logging.getLogger(__name__)

class AuthService:
    @staticmethod
    async def create_user(user_in: UserCreate) -> UserInDB:
        """
        Creates a new user in the database.
        Checks if the email already exists.
        """
        db = DatabaseService.get_database(settings.DATABASE_NAME)
        users_collection: Collection = db["users"]
        
        # Check if user already exists
        existing_user = await users_collection.find_one({"email": user_in.email})
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Create new user document
        hashed_password = get_password_hash(user_in.password)
        
        user_db = UserInDB(
            email=user_in.email,
            password=hashed_password
        )
        
        # Insert into DB
        new_user = await users_collection.insert_one(user_db.model_dump())
        
        if not new_user.inserted_id:
             raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )
            
        return user_db
