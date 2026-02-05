import logging
from typing import Optional
import pymongo
from app.services.database import DatabaseService
from app.models.user import UserInDB

logger = logging.getLogger(__name__)

class UserService:
    def __init__(self):
        # We will retrieve the collection dynamically to ensure DB is connected
        self.collection_name = "users"

    def _get_collection(self):
        return DatabaseService.get_collection("ai_interviewer_db", self.collection_name)
    
    async def ensure_indexes(self):
        """
        Creates a unique index on the email field.
        Call this during application startup.
        """
        try:
            collection = self._get_collection()
            # unique=True ensures DB rejects duplicates
            await collection.create_index(
                [("email", pymongo.ASCENDING)], 
                unique=True
            )
            logger.info("Verified unique index on 'users.email'")
        except Exception as e:
            logger.error(f"Could not create index: {e}")

    #Fetch a user by username. 
    #Returns None if not found.
    async def get_user_by_email(self, email: str) -> Optional[UserInDB]:
        try:
            collection = self._get_collection()
            user_doc = await collection.find_one({"email": email})
            if user_doc:
                return UserInDB(**user_doc)
        except Exception as e:
            logger.error(f"Error fetching user {email}: {e}")
        return None

    async def create_user(self, user_in_db: UserInDB):
        try:
            collection = self._get_collection()
            user_dict = user_in_db.model_dump()
            
            result = await collection.insert_one(user_dict)
            logger.info(f"Created user: {user_in_db.email}")
            return result.inserted_id
        except pymongo.errors.DuplicateKeyError:
            # This catches the race condition if two people sign up at the exact same time
            logger.warning(f"Duplicate email attempt: {user_in_db.email}")
            raise ValueError("Email already exists")
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise e