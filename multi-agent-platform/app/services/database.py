from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class DatabaseService:
    client: Optional[AsyncIOMotorClient] = None
    
    @classmethod
    async def connect_db(cls, mongodb_url: str):
        """Connect to MongoDB"""
        try:
            cls.client = AsyncIOMotorClient(mongodb_url)
            await cls.client.admin.command('ping')
            logger.info("✅ Connected to MongoDB")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            raise
    
    @classmethod
    async def close_db(cls):
        """Close MongoDB connection"""
        if cls.client:
            cls.client.close()
            logger.info("🔌 MongoDB connection closed")
    
    @classmethod
    def get_database(cls, db_name: str):
        """Get database instance"""
        if not cls.client:
            raise Exception("Database not connected")
        return cls.client[db_name]
    
    @classmethod
    def get_collection(cls, db_name: str, collection_name: str):
        """Get collection instance"""
        db = cls.get_database(db_name)
        return db[collection_name]
